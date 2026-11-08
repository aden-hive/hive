//! What the app remembers between runs: where its window was, and what it had open.

use std::path::PathBuf;

use gpui_kit::{Bounds, Pixels, WindowBounds, point, px, size};
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Default)]
pub struct Saved {
    pub window: Option<SavedBounds>,
    /// The last route, as `--open` takes it, and the server it was on: a queen or colony on one
    /// server means nothing on another.
    pub route: Option<String>,
    pub server: Option<String>,
}

/// A window's place in logical pixels, and whether it was maximized.
#[derive(Serialize, Deserialize, Clone, Copy, Debug, PartialEq)]
pub struct SavedBounds {
    x: f32,
    y: f32,
    width: f32,
    height: f32,
    maximized: bool,
}

impl SavedBounds {
    pub fn of(bounds: WindowBounds) -> Option<Self> {
        let (b, maximized) = match bounds {
            WindowBounds::Windowed(b) => (b, false),
            WindowBounds::Maximized(b) => (b, true),
            // A fullscreen window reopens at its restore size rather than taking over the screen.
            WindowBounds::Fullscreen(b) => (b, false),
        };
        Some(Self {
            x: b.origin.x.into(),
            y: b.origin.y.into(),
            width: b.size.width.into(),
            height: b.size.height.into(),
            maximized,
        })
    }

    pub fn bounds(self) -> Bounds<Pixels> {
        Bounds { origin: point(px(self.x), px(self.y)), size: size(px(self.width), px(self.height)) }
    }

    pub fn window_bounds(self) -> WindowBounds {
        if self.maximized { WindowBounds::Maximized(self.bounds()) } else { WindowBounds::Windowed(self.bounds()) }
    }
}

/// `%APPDATA%\hive-desktop\state.json`, or the XDG config directory elsewhere.
fn path() -> Option<PathBuf> {
    let base = std::env::var_os("APPDATA")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("XDG_CONFIG_HOME").map(PathBuf::from))
        .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".config")))?;
    Some(base.join("hive-desktop").join("state.json"))
}

/// What was saved last time; nothing if there's no file or it can't be read.
pub fn load() -> Saved {
    path()
        .and_then(|p| std::fs::read_to_string(p).ok())
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_default()
}

/// Change what's saved. Failing to save only costs the next start its memory, so errors are dropped.
pub fn update(change: impl FnOnce(&mut Saved)) {
    let Some(path) = path() else { return };
    let mut saved = load();
    change(&mut saved);
    let Ok(text) = serde_json::to_string_pretty(&saved) else { return };
    if let Some(dir) = path.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    // Written aside and moved into place, so a crash mid-write leaves the old file whole.
    let temp = path.with_extension("json.tmp");
    if std::fs::write(&temp, text).is_ok() {
        let _ = std::fs::rename(&temp, &path);
    }
}

#[cfg(test)]
mod tests {
    // Not `super::*`: GPUI's own `test` macro would shadow the standard one.
    use super::SavedBounds;
    use gpui_kit::{Bounds, WindowBounds, point, px, size};

    #[test]
    fn keeps_a_maximized_windows_restore_size() {
        let restore = Bounds { origin: point(px(40.), px(30.)), size: size(px(1200.), px(800.)) };
        let saved = SavedBounds::of(WindowBounds::Maximized(restore)).unwrap();

        assert_eq!(saved.window_bounds(), WindowBounds::Maximized(restore));
        assert_eq!(
            SavedBounds::of(WindowBounds::Fullscreen(restore)).unwrap().window_bounds(),
            WindowBounds::Windowed(restore)
        );
    }
}
