//! A native Hive client. It talks to a running `hive serve` over the same HTTP API as the web
//! dashboard.

mod api;
mod avatars;
mod bg;
mod chat;
mod chat_view;
mod colony_view;
mod live;
mod pages;
mod plan;
mod portrait;
mod sentinel;
mod shell;
mod state;
mod ui;

use std::borrow::Cow;

use gpui_kit::component::{Theme, ThemeRegistry};
use gpui_kit::*;

use api::{Api, HiveApi};
use shell::{Route, Shell};

/// Where `hive serve` listens unless told otherwise (`framework/loader/cli.py`).
const DEFAULT_SERVER: &str = "http://127.0.0.1:8787";

/// Geist and Geist Mono, the web dashboard's typefaces (SIL Open Font License, `assets/fonts/OFL.txt`).
const FONTS: [&[u8]; 6] = [
    include_bytes!("../assets/fonts/Geist-Regular.ttf"),
    include_bytes!("../assets/fonts/Geist-Medium.ttf"),
    include_bytes!("../assets/fonts/Geist-SemiBold.ttf"),
    include_bytes!("../assets/fonts/Geist-Bold.ttf"),
    include_bytes!("../assets/fonts/GeistMono-Regular.ttf"),
    include_bytes!("../assets/fonts/GeistMono-Medium.ttf"),
];

/// The web dashboard's light and dark colors (`frontend/src/index.css`), as GPUI Kit themes.
const THEMES: &str = include_str!("../assets/themes/hive.json");

/// Install Hive's fonts and make its themes the ones light and dark mode use.
fn install_look(cx: &mut App) {
    // Without the fonts, the theme's family falls back to the system font; still usable.
    let _ = cx.text_system().add_fonts(FONTS.iter().map(|font| Cow::Borrowed(*font)).collect());
    let registry = ThemeRegistry::global_mut(cx);
    if registry.load_themes_from_str(THEMES).is_err() {
        return;
    }
    let light = registry.themes().get("Hive Light").cloned();
    let dark = registry.themes().get("Hive Dark").cloned();
    let theme = Theme::global_mut(cx);
    if let Some(light) = light {
        theme.light_theme = light;
    }
    if let Some(dark) = dark {
        theme.dark_theme = dark;
    }
}

/// The value after `--name` on the command line.
fn arg(name: &str) -> Option<String> {
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        if arg == name {
            return args.next();
        }
    }
    None
}

fn main() {
    // `--server URL`, else `HIVE_URL`, else where `hive serve` listens by default.
    let server =
        arg("--server").or_else(|| std::env::var("HIVE_URL").ok()).unwrap_or_else(|| DEFAULT_SERVER.to_string());
    let saved = state::load();
    // `--open` wins; otherwise pick up where the last run left off.
    let last_route = saved.route.filter(|_| saved.server.as_deref() == Some(server.as_str()));
    let open = arg("--open").or(last_route).and_then(|s| Route::parse(&s));
    let api = Api::new(&server);
    // The full Lucide set (about 1 MB), so pages can use any icon the web dashboard does.
    gpui_kit::application().with_assets(gpui_kit::assets::AllAssets).run(move |cx| {
        gpui_kit::init(cx);
        install_look(cx);
        cx.set_global(HiveApi(api));
        cx.bind_keys([
            KeyBinding::new("ctrl-f", chat_view::Find, Some("ChatView")),
            KeyBinding::new("cmd-f", chat_view::Find, Some("ChatView")),
            KeyBinding::new("ctrl-k", shell::OpenSwitcher, Some("Shell")),
            KeyBinding::new("cmd-k", shell::OpenSwitcher, Some("Shell")),
            KeyBinding::new("escape", shell::CloseSwitcher, Some("Switcher")),
        ]);
        // The last place, unless no screen shows it any more (say, a monitor was unplugged).
        let last = saved.window.filter(|w| cx.displays().iter().any(|d| d.bounds().intersects(&w.bounds())));
        let options = WindowOptions {
            titlebar: Some(TitlebarOptions { title: Some("Hive".into()), ..Default::default() }),
            window_bounds: Some(
                last.map(|w| w.window_bounds())
                    .unwrap_or_else(|| WindowBounds::Windowed(Bounds::centered(None, size(px(1320.), px(860.)), cx))),
            ),
            ..Default::default()
        };
        gpui_kit::open_window(options, cx, |window, cx| {
            // Light or dark as the system is, and follow it when it changes.
            Theme::sync_system_appearance(Some(window), cx);
            cx.new(|cx| {
                cx.observe_window_appearance(window, |_, window, cx| Theme::sync_system_appearance(Some(window), cx))
                    .detach();
                Shell::new(open, window, cx)
            })
        })
        .expect("open the window");
    });
}
