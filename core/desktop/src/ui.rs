//! Small pieces of UI the views share.

use std::time::{SystemTime, UNIX_EPOCH};

use gpui_kit::assets::IconName;
use gpui_kit::base::{h_flex, v_flex};
use gpui_kit::component::button::{Button, ButtonVariants as _};
use gpui_kit::component::text::{TextView, TextViewStyle};
use gpui_kit::component::{Sizable as _, StyledExt as _, Theme};
use gpui_kit::*;

/// Markdown as the web renders it: white code blocks with a border and a copy button, and headings
/// only a little larger than the text, since they sit inside chat bubbles and cards.
pub fn markdown(id: impl Into<ElementId>, text: impl Into<SharedString>, theme: &Theme) -> TextView {
    let code_block = StyleRefinement::default().bg(theme.popover).border_1().border_color(theme.border);
    let style = TextViewStyle::default()
        .heading_font_size(|level, base| match level {
            1 => base * 1.2,
            2 => base * 1.12,
            3 => base * 1.06,
            _ => base,
        })
        .code_block(code_block);
    let muted = theme.muted_foreground;
    TextView::markdown(id, text).style(style).selectable(true).code_block_actions(move |block, _, _| {
        let code = block.code();
        h_flex().gap_1().children(block.lang().map(|lang| div().text_xs().text_color(muted).child(lang))).child(
            Button::new("copy-code")
                .xsmall()
                .ghost()
                .icon(IconName::Copy)
                .tooltip("Copy")
                .on_click(move |_, _, cx| cx.write_to_clipboard(ClipboardItem::new_string(code.to_string()))),
        )
    })
}

/// A queen's title as the web sidebar shows it ("Head of Growth" → "Growth").
pub fn role(title: &str) -> &str {
    title.strip_prefix("Head of ").unwrap_or(title)
}

/// A round badge with the name's first letter.
pub fn initial_avatar(name: &str, size: Pixels, theme: &Theme) -> Div {
    let initial = name.chars().next().map(|c| c.to_uppercase().to_string()).unwrap_or_default();
    div()
        .size(size)
        .flex_shrink_0()
        .rounded_full()
        .flex()
        .items_center()
        .justify_center()
        // A pale honey disc with the letter in honey, as the web shows a queen without a portrait.
        .bg(theme.primary.opacity(0.14))
        .text_color(theme.primary)
        .text_size(size * 0.46)
        .font_semibold()
        .child(initial)
}

/// A small rounded label in honey, e.g. a queen's title beside her name.
pub fn pill(text: impl Into<SharedString>, theme: &Theme) -> Div {
    div()
        .flex_shrink_0()
        .px_2()
        .py_0p5()
        .rounded_full()
        .border_1()
        .border_color(theme.primary.opacity(0.35))
        .bg(theme.primary.opacity(0.08))
        .text_xs()
        .text_color(theme.primary)
        .child(text.into())
}

/// A small coloured dot, e.g. a session's state.
pub fn dot(color: Hsla) -> Div {
    div().size(px(8.)).flex_shrink_0().rounded_full().bg(color)
}

/// The frame every library or settings page sits in: a title, a line on what it's for, and a body
/// that scrolls. Both sit in a centred column, as on the web; content roots take
/// `.w_full().max_w(px(880.)).mx_auto()` to line up with the header.
pub fn page(
    id: &'static str,
    title: impl Into<SharedString>,
    lede: impl Into<SharedString>,
    theme: &Theme,
) -> (Div, Stateful<Div>) {
    let header = v_flex()
        .w_full()
        .max_w(px(880.))
        .mx_auto()
        .gap_1()
        .px_8()
        .pt_8()
        .pb_2()
        .child(div().text_xl().font_semibold().child(title.into()))
        .child(div().text_sm().text_color(theme.muted_foreground).child(lede.into()));
    let body = div().id(id).flex_1().min_h_0().overflow_y_scroll();
    (header, body)
}

/// A titled group within a page.
pub fn section(title: impl Into<SharedString>, theme: &Theme) -> Div {
    v_flex().gap_2().child(div().text_sm().font_semibold().text_color(theme.foreground).child(title.into()))
}

pub fn error_line(text: impl Into<SharedString>, theme: &Theme) -> Div {
    div().text_sm().text_color(theme.danger).child(text.into())
}

pub fn muted(text: impl Into<SharedString>, theme: &Theme) -> Div {
    div().text_sm().text_color(theme.muted_foreground).child(text.into())
}

/// A bordered row, the page's list item.
pub fn card(theme: &Theme) -> Div {
    // White on the warm page, as the web's cards are.
    h_flex().gap_3().px_4().py_3().rounded_lg().border_1().border_color(theme.border).bg(theme.popover)
}

/// "just now", "5m ago", "3h ago", "2d ago", for a Unix time in seconds.
pub fn ago(epoch_seconds: f64) -> String {
    let now = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(epoch_seconds);
    let secs = (now - epoch_seconds).max(0.0) as u64;
    match secs {
        0..60 => "just now".into(),
        60..3600 => format!("{}m ago", secs / 60),
        3600..86400 => format!("{}h ago", secs / 3600),
        _ => format!("{}d ago", secs / 86400),
    }
}

/// Text cut to `max` characters, with an ellipsis when something was cut.
pub fn clip(text: &str, max: usize) -> String {
    let mut out: String = text.chars().take(max).collect();
    if text.chars().nth(max).is_some() {
        out.push('…');
    }
    out
}
