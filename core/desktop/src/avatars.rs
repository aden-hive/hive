//! Queens' uploaded pictures, fetched once and kept for the life of the app.

use std::collections::HashMap;
use std::sync::Arc;

use gpui_kit::component::ActiveTheme as _;
use gpui_kit::*;

use crate::api::{Queen, api};
use crate::ui;

enum Picture {
    Loading,
    Ready(Arc<Image>),
    /// No usable picture; show the initial.
    Missing,
}

#[derive(Default)]
struct Avatars {
    pictures: HashMap<String, Picture>,
    /// Drawn portraits by queen and size in pixels.
    portraits: HashMap<(String, u32), Arc<Image>>,
}

impl Global for Avatars {}

/// The image format, told from the file's first bytes, as the server doesn't always say.
pub(crate) fn sniff(bytes: &[u8]) -> Option<ImageFormat> {
    match bytes {
        [0x89, b'P', b'N', b'G', ..] => Some(ImageFormat::Png),
        [0xFF, 0xD8, ..] => Some(ImageFormat::Jpeg),
        [b'G', b'I', b'F', ..] => Some(ImageFormat::Gif),
        [b'R', b'I', b'F', b'F', _, _, _, _, b'W', b'E', b'B', b'P', ..] => Some(ImageFormat::Webp),
        _ if bytes.trim_ascii_start().starts_with(b"<") => Some(ImageFormat::Svg),
        _ => None,
    }
}

/// The queen's picture if she has one, else her drawn portrait, else her initial. The first call
/// for a picture starts the download and shows the portrait or initial until it lands.
pub fn avatar(queen: &Queen, size: Pixels, cx: &mut App) -> AnyElement {
    cx.default_global::<Avatars>();
    if !queen.has_avatar {
        return match portrait(queen, size, cx) {
            Some(image) => div()
                .size(size)
                .flex_shrink_0()
                .rounded_full()
                // The web's `bg-primary/15` behind the glyph.
                .bg(cx.theme().primary.opacity(0.15))
                // Children clip to rectangles, so the image rounds itself; the shirt's corners would show.
                .child(img(image).size_full().rounded_full())
                .into_any_element(),
            None => ui::initial_avatar(&queen.name, size, cx.theme()).into_any_element(),
        };
    }
    match cx.global::<Avatars>().pictures.get(&queen.id) {
        Some(Picture::Ready(image)) => {
            return img(image.clone()).size(size).flex_shrink_0().rounded_full().into_any_element();
        }
        Some(_) => {}
        None => fetch(queen.id.clone(), cx),
    }
    ui::initial_avatar(&queen.name, size, cx.theme()).into_any_element()
}

/// Her portrait glyph at `size`, drawn once per size. The SVG is drawn at twice the size, as GPUI
/// draws an SVG at its own size and scales the bitmap: drawn at 100 px and scaled down, its thin
/// strokes break up. Twice covers 1.5x and 2x screens; on 1x it's scaled down, which stays smooth.
fn portrait(queen: &Queen, size: Pixels, cx: &mut App) -> Option<Arc<Image>> {
    let descriptor = queen.portrait.as_ref().filter(|p| p.is_object())?;
    let pixels = (f32::from(size) * 2.).round() as u32;
    let key = (queen.id.clone(), pixels);
    if let Some(image) = cx.global::<Avatars>().portraits.get(&key) {
        return Some(image.clone());
    }
    let svg = crate::portrait::svg(descriptor, crate::portrait::ACCENT).replacen(
        "<svg ",
        &format!("<svg width=\"{pixels}\" height=\"{pixels}\" "),
        1,
    );
    let image = Arc::new(Image::from_bytes(ImageFormat::Svg, svg.into_bytes()));
    cx.global_mut::<Avatars>().portraits.insert(key, image.clone());
    Some(image)
}

/// Drop every kept picture so the next draw fetches it again, e.g. after one was replaced.
pub fn forget_all(cx: &mut App) {
    if cx.has_global::<Avatars>() {
        let avatars = cx.global_mut::<Avatars>();
        avatars.pictures.clear();
        avatars.portraits.clear();
    }
}

fn fetch(queen_id: String, cx: &mut App) {
    cx.global_mut::<Avatars>().pictures.insert(queen_id.clone(), Picture::Loading);
    let api = api(cx);
    let path = format!("/queen/{queen_id}/avatar");
    cx.spawn(async move |cx| {
        let bytes = cx.background_spawn(async move { api.bytes(&path) }).await;
        cx.update(|cx| {
            let picture = match bytes {
                Ok(bytes) => match sniff(&bytes) {
                    Some(format) => Picture::Ready(Arc::new(Image::from_bytes(format, bytes))),
                    None => Picture::Missing,
                },
                Err(_) => Picture::Missing,
            };
            cx.global_mut::<Avatars>().pictures.insert(queen_id, picture);
            cx.refresh_windows();
        });
    })
    .detach();
}
