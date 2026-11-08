//! A queen's drawn portrait, from the descriptor in her profile: the web dashboard's
//! `QueenPortraitGlyph` (with its dashed honeycomb frame), as SVG markup for `ImageFormat::Svg`.

use std::borrow::Cow;
use std::fmt::Write as _;

use serde_json::Value;

/// The web's accent, `oklch(0.62 0.14 70)`, in sRGB. It sits just outside sRGB, so this is the
/// clipped value a browser shows on an sRGB screen.
pub const ACCENT: &str = "#BB7400";

const STROKE: &str = "#1B1814";

const FACE_SHAPES: &[(&str, &str)] = &[
    ("oval", "M50,28 C68,28 76,46 76,62 C76,80 64,90 50,90 C36,90 24,80 24,62 C24,46 32,28 50,28 Z"),
    ("round", "M50,30 C70,30 78,48 78,62 C78,80 66,90 50,90 C34,90 22,80 22,62 C22,48 30,30 50,30 Z"),
    ("long", "M50,26 C66,26 74,46 74,64 C74,84 62,94 50,94 C38,94 26,84 26,64 C26,46 34,26 50,26 Z"),
    ("rect", "M50,28 C66,28 74,42 74,58 L74,72 C74,86 62,92 50,92 C38,92 26,86 26,72 L26,58 C26,42 34,28 50,28 Z"),
    ("square", "M50,30 L72,32 L74,72 L60,90 L40,90 L26,72 L28,32 Z"),
];

/// Each cut's crown and, for some, a side piece drawn over it.
const HAIR_PATHS: &[(&str, Option<&str>, Option<&str>)] = &[
    (
        "short",
        Some("M28,46 C28,32 38,22 50,22 C62,22 72,32 72,46 C70,42 64,38 58,38 C54,38 50,40 46,40 C42,40 38,42 30,46 Z"),
        None,
    ),
    ("short-back", Some("M30,48 C30,32 40,22 50,22 C60,22 70,32 70,48 C66,42 60,40 50,40 C40,40 34,42 30,48 Z"), None),
    ("short-bob", Some("M26,52 C26,30 38,20 50,20 C62,20 74,30 74,52 L72,58 L70,46 L30,46 L28,58 Z"), None),
    ("short-grey", Some("M30,46 C30,32 40,22 50,22 C60,22 70,32 70,46 C66,42 60,40 50,40 C40,40 34,42 30,46 Z"), None),
    ("short-thin", Some("M34,42 C34,32 42,24 50,24 C58,24 66,32 66,42 C62,40 56,38 50,38 C44,38 38,40 34,42 Z"), None),
    ("crop", Some("M30,42 C30,30 40,22 50,22 C60,22 70,30 70,42 C66,38 60,36 50,36 C40,36 34,38 30,42 Z"), None),
    ("crop-thin", Some("M34,40 C34,30 42,24 50,24 C58,24 66,30 66,40 C62,38 56,36 50,36 C44,36 38,38 34,40 Z"), None),
    (
        "side-back",
        Some("M28,48 C28,32 38,22 50,22 C62,22 72,32 72,48 C66,40 56,40 46,42 C40,42 34,42 28,48 Z"),
        Some("M70,40 C72,46 70,52 66,54 L62,42 Z"),
    ),
    (
        "side-back-grey",
        Some("M28,48 C28,32 38,22 50,22 C62,22 72,32 72,48 C66,40 56,40 46,42 C40,42 34,42 28,48 Z"),
        Some("M70,40 C72,46 70,52 66,54 L62,42 Z"),
    ),
    (
        "side-bushy-grey",
        Some("M22,46 C22,30 36,18 50,18 C64,18 78,30 78,46 C74,38 66,38 56,40 C46,42 36,38 22,46 Z"),
        Some("M70,38 C76,46 74,56 66,58 L60,42 Z"),
    ),
    ("side-short", Some("M28,46 C28,32 38,22 50,22 C62,22 72,32 72,46 C68,40 56,38 46,40 C40,40 34,42 28,46 Z"), None),
    (
        "side-short-grey",
        Some("M28,46 C28,32 38,22 50,22 C62,22 72,32 72,46 C68,40 56,38 46,40 C40,40 34,42 28,46 Z"),
        None,
    ),
    (
        "parted",
        Some("M26,50 C26,30 38,20 50,20 C62,20 74,30 74,50 C70,40 60,38 52,42 L50,30 L48,42 C40,38 30,40 26,50 Z"),
        None,
    ),
    (
        "swept-front",
        Some(
            "M28,48 C28,32 38,22 50,22 C62,22 72,32 72,48 C70,40 60,38 52,40 C46,42 38,46 32,52 L34,46 C32,46 30,46 28,48 Z",
        ),
        None,
    ),
    (
        "slick-back",
        Some(
            "M30,46 C30,30 40,22 50,22 C60,22 70,30 70,46 C68,40 64,38 58,38 C56,38 54,38 52,38 L50,30 L48,38 C44,38 38,40 30,46 Z",
        ),
        None,
    ),
    (
        "wave-long",
        Some("M22,52 C22,30 38,20 50,20 C62,20 78,30 78,52 C72,44 66,50 60,46 C56,50 50,46 44,50 C38,46 30,52 22,52 Z"),
        Some("M22,54 C20,62 22,72 28,76 L30,52 Z M78,54 C80,62 78,72 72,76 L70,52 Z"),
    ),
    (
        "wild-curly",
        Some("M22,42 C24,26 38,16 50,16 C62,16 76,26 78,42 C74,38 66,42 60,32 C56,42 50,38 44,32 C38,42 28,38 22,42 Z"),
        None,
    ),
    (
        "wild-curly-grey",
        Some("M22,42 C24,26 38,16 50,16 C62,16 76,26 78,42 C74,38 66,42 60,32 C56,42 50,38 44,32 C38,42 28,38 22,42 Z"),
        None,
    ),
    (
        "curls-fringe",
        Some(
            "M26,46 C26,30 38,22 50,22 C62,22 74,30 74,46 C70,44 66,46 62,42 C58,46 54,42 50,46 C46,42 42,46 38,42 C34,46 30,44 26,46 Z",
        ),
        None,
    ),
    (
        "pulled-tight",
        Some("M30,42 C30,30 40,22 50,22 C60,22 70,30 70,42 C66,40 60,38 50,38 C40,38 34,40 30,42 Z"),
        Some("M70,40 C76,50 74,60 70,66 L66,42 Z M30,40 C24,50 26,60 30,66 L34,42 Z"),
    ),
    ("long-straight", Some("M22,80 C22,40 32,20 50,20 C68,20 78,40 78,80 L70,76 L70,46 L30,46 L30,76 Z"), None),
    (
        "long-wavy",
        Some(
            "M22,80 C22,40 32,20 50,20 C68,20 78,40 78,80 C76,72 72,74 70,68 L70,46 L30,46 L30,68 C28,74 24,72 22,80 Z",
        ),
        None,
    ),
    ("bob-long", Some("M22,72 C22,32 34,18 50,18 C66,18 78,32 78,72 L72,66 L70,46 L30,46 L28,66 Z"), None),
    (
        "bob-sharp-bangs",
        Some("M22,54 L22,30 C22,22 36,18 50,18 C64,18 78,22 78,30 L78,54 L70,52 L66,40 L34,40 L30,52 Z"),
        Some("M30,40 L34,52 L34,40 Z M70,40 L66,52 L66,40 Z"),
    ),
    ("bald-shine", None, Some("M50,24 C46,26 44,28 44,32 L48,30 Z")),
    ("bald", None, None),
];

const MOUTH_PATHS: &[(&str, &str)] = &[
    ("flat", "M44,76 L56,76"),
    ("smile", "M43,75 Q50,80 57,75"),
    ("smile-soft", "M44,76 Q50,79 56,76"),
    ("smile-broad", "M42,74 Q50,82 58,74"),
    ("smirk", "M44,76 Q50,79 56,75"),
];

const EYE_Y: f64 = 58.;
const EYE_XL: f64 = 41.;
const EYE_XR: f64 = 59.;
const BROW_Y: f64 = EYE_Y - 6.;

/// The portrait as a 100×100 SVG, the same shapes and colors the web draws for this descriptor.
/// A missing field, or one JavaScript reads as false (null, "", 0), takes the web's default.
/// `accent` stands in for the web's accent color; [`ACCENT`] is its sRGB value.
///
/// GPUI rasterizes an SVG image once at its intrinsic size (100×100 here) and the GPU scales that
/// bitmap, which breaks thin strokes into dashes below about 50 device pixels. For a small avatar,
/// give the root `width` and `height` in device pixels.
pub fn svg(descriptor: &Value, accent: &str) -> String {
    let p = descriptor;
    let accent = esc(accent);
    let skin = esc(&or(p, "skin", "#F1D6BA")).into_owned();
    let hair = esc(&or(p, "hair", "#3B312A")).into_owned();
    let cut = or(p, "cut", "short");
    let face = or(p, "face", "oval");
    let eyes = or(p, "eyes", "kind");
    let mouth = or(p, "mouth", "flat");

    let face_shape = find(FACE_SHAPES, &face).unwrap_or(FACE_SHAPES[0].1);
    let (_, hair_top, hair_side) = HAIR_PATHS.iter().find(|(name, ..)| *name == cut).copied().unwrap_or(HAIR_PATHS[0]);
    let mouth_shape = find(MOUTH_PATHS, &mouth).unwrap_or(MOUTH_PATHS[0].1);

    let eye_r = if eyes == "wide" { 2.6 } else { 2.0 };
    let brow_arch = if is(p, "brow", "arched") { -1.5 } else { 0. };

    let show_brow = !truthy(p.get("glasses")) || is(p, "glasses", "sun");
    let show_eyes = !is(p, "glasses", "sun");

    let mut s = String::with_capacity(4096);
    s.push_str(r#"<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet">"#);

    // The inset dashed honeycomb frame.
    let hex = "50,4 92,28 92,72 50,96 8,72 8,28";
    let _ = write!(s, r#"<polygon points="{hex}" fill="{accent}" opacity="0.08"/>"#);
    let _ = write!(
        s,
        r#"<polygon points="{hex}" fill="none" stroke="{accent}" stroke-opacity="0.4" stroke-width="0.8" stroke-dasharray="2 2"/>"#
    );

    if is(p, "shirt", "tee-black") || is(p, "neck", "turtleneck") {
        let y = if is(p, "neck", "turtleneck") { 88 } else { 92 };
        let _ = write!(s, r##"<rect x="26" y="{y}" width="48" height="12" fill="#1F1B17"/>"##);
    } else if is(p, "shirt", "tee-grey") {
        s.push_str(r##"<rect x="26" y="92" width="48" height="12" fill="#5C544A"/>"##);
    } else if is(p, "shirt", "shirt-tie") {
        let _ = write!(
            s,
            r##"<g><path d="M26,94 L42,90 L50,94 L58,90 L74,94 L74,100 L26,100 Z" fill="#F4F1E8"/><path d="M48,90 L52,90 L54,100 L46,100 Z" fill="{accent}"/><path d="M48,90 L50,93 L52,90 Z" fill="#1F1B17"/></g>"##
        );
    } else if is(p, "shirt", "shirt-blue") {
        s.push_str(
            r##"<g><path d="M26,94 L42,89 L50,93 L58,89 L74,94 L74,100 L26,100 Z" fill="#7AA0BB"/><path d="M42,89 L46,98 M58,89 L54,98" stroke="#5A8099" stroke-width="0.8"/></g>"##,
        );
    } else if is(p, "shirt", "shirt-aloha") {
        s.push_str(r##"<g><path d="M26,92 L42,88 L50,92 L58,88 L74,92 L74,100 L26,100 Z" fill="#E8917A"/>"##);
        for (cx, cy) in [(34, 96), (42, 98), (58, 96), (66, 98)] {
            let _ = write!(s, r##"<circle cx="{cx}" cy="{cy}" r="1.2" fill="#F4F1E8"/>"##);
        }
        s.push_str("</g>");
    } else if is(p, "shirt", "sweater-vee") {
        s.push_str(
            r##"<g><rect x="26" y="92" width="48" height="12" fill="#9C8E78"/><path d="M42,92 L50,98 L58,92 L58,94 L50,100 L42,94 Z" fill="#F4F1E8"/></g>"##,
        );
    } else if truthy(p.get("leather")) {
        s.push_str(r##"<path d="M26,92 L40,88 L60,88 L74,92 L74,100 L26,100 Z" fill="#0F0E0C"/>"##);
    } else if is(p, "collar", "jabot") {
        s.push_str(
            r##"<g><rect x="26" y="92" width="48" height="12" fill="#1F1B17"/><path d="M40,90 L50,86 L60,90 L60,100 L40,100 Z" fill="#FFFFFF"/><path d="M44,90 L46,98 M50,88 L50,100 M54,90 L52,98" stroke="#D8D2C5" stroke-width="0.8" fill="none"/></g>"##,
        );
    } else if is(p, "collar", "robe") {
        s.push_str(
            r##"<g><rect x="26" y="92" width="48" height="12" fill="#1F1B17"/><path d="M42,92 L50,96 L58,92" stroke="#3C342B" stroke-width="1.2" fill="none"/></g>"##,
        );
    } else {
        let _ = write!(s, r#"<rect x="42" y="86" width="16" height="14" fill="{skin}"/>"#);
    }

    let _ = write!(s, r#"<path d="{face_shape}" fill="{skin}" stroke="{STROKE}" stroke-width="1"/>"#);

    for cx in [36, 64] {
        let _ = write!(s, r#"<ellipse cx="{cx}" cy="68" rx="3" ry="1.6" fill="{accent}" opacity="0.18"/>"#);
    }

    if let Some(top) = hair_top {
        let _ = write!(s, r#"<path d="{top}" fill="{hair}" stroke="{STROKE}" stroke-width="0.8"/>"#);
    }
    if let Some(side) = hair_side {
        let _ = write!(s, r#"<path d="{side}" fill="{hair}" stroke="{STROKE}" stroke-width="0.6" opacity="0.95"/>"#);
    }

    if cut == "bald-shine" {
        s.push_str(r#"<path d="M40,32 Q50,26 60,32" stroke="rgba(255,255,255,0.45)" stroke-width="1.2" fill="none"/>"#);
    }

    if show_brow {
        if is(p, "brow", "bushy") {
            let _ = write!(
                s,
                r#"<g fill="{hair}"><path d="M{},{} q5,-2 11,1 q-5.5,2 -11,-1 Z"/><path d="M{},{} q5.5,-3 11,1 q-5,2 -11,-1 Z"/></g>"#,
                EYE_XL - 5.5,
                BROW_Y - 1.,
                EYE_XR - 5.5,
                BROW_Y - 1.,
            );
        } else {
            let _ = write!(
                s,
                r#"<g stroke="{STROKE}" stroke-width="1.4" stroke-linecap="round"><line x1="{}" y1="{}" x2="{}" y2="{}"/><line x1="{}" y1="{}" x2="{}" y2="{}"/></g>"#,
                EYE_XL - 4.,
                BROW_Y,
                EYE_XL + 4.,
                BROW_Y + brow_arch,
                EYE_XR - 4.,
                BROW_Y + brow_arch,
                EYE_XR + 4.,
                BROW_Y,
            );
        }
    }

    if show_eyes {
        let _ = write!(
            s,
            r#"<g fill="{STROKE}"><circle cx="{EYE_XL}" cy="{EYE_Y}" r="{eye_r}"/><circle cx="{EYE_XR}" cy="{EYE_Y}" r="{eye_r}"/></g>"#
        );
    }

    glasses(&mut s, p);

    let _ = write!(
        s,
        r#"<path d="M50,62 L48,70 L52,70" fill="none" stroke="{STROKE}" stroke-width="1" stroke-linejoin="round" opacity="0.55"/>"#
    );

    if truthy(p.get("moustache")) {
        let _ = write!(s, r#"<path d="M40,73 Q50,78 60,73 L58,75 Q50,77 42,75 Z" fill="{hair}"/>"#);
    }

    let _ = write!(
        s,
        r#"<path d="{mouth_shape}" fill="none" stroke="{STROKE}" stroke-width="1.4" stroke-linecap="round"/>"#
    );

    if is(p, "beard", "goatee-stubble") {
        let _ = write!(
            s,
            r#"<g><path d="M40,80 C44,86 56,86 60,80 L60,84 C56,88 44,88 40,84 Z" fill="{hair}" opacity="0.55"/><path d="M46,80 L46,86 L54,86 L54,80 Z" fill="{hair}" opacity="0.85"/></g>"#
        );
    }
    if is(p, "beard", "stubble") {
        let _ = write!(
            s,
            r#"<path d="M36,76 C40,86 60,86 64,76 L64,82 C58,88 42,88 36,82 Z" fill="{hair}" opacity="0.4"/>"#
        );
    }
    if is(p, "beard", "full") || is(p, "beard", "full-grey") {
        let fill = if is(p, "beard", "full-grey") { "#C8BEB0" } else { hair.as_str() };
        let _ = write!(
            s,
            r#"<g><path d="M28,66 C30,86 42,94 50,94 C58,94 70,86 72,66 C68,80 56,80 50,80 C44,80 32,80 28,66 Z" fill="{fill}"/><path d="M40,73 Q50,77 60,73 L58,75 Q50,77 42,75 Z" fill="{fill}"/></g>"#
        );
    }

    if truthy(p.get("earring")) {
        let _ = write!(s, r#"<circle cx="74" cy="66" r="1.6" fill="{accent}"/>"#);
    }

    s.push_str("</svg>");
    s
}

fn glasses(s: &mut String, p: &Value) {
    let (l, r, y) = (EYE_XL, EYE_XR, EYE_Y);
    let frame = match p.get("glasses").and_then(Value::as_str) {
        Some("round") => format!(
            r#"<g fill="none" stroke="{STROKE}" stroke-width="1.4"><circle cx="{l}" cy="{y}" r="6" fill="rgba(255,255,255,0.18)"/><circle cx="{r}" cy="{y}" r="6" fill="rgba(255,255,255,0.18)"/><line x1="{}" y1="{y}" x2="{}" y2="{y}"/></g>"#,
            l + 6.,
            r - 6.,
        ),
        Some("round-rimless") => format!(
            r#"<g fill="none" stroke="{STROKE}" stroke-width="0.7" opacity="0.85"><circle cx="{l}" cy="{y}" r="6"/><circle cx="{r}" cy="{y}" r="6"/><line x1="{}" y1="{y}" x2="{}" y2="{y}"/></g>"#,
            l + 6.,
            r - 6.,
        ),
        Some("round-thick") => format!(
            r#"<g fill="none" stroke="{STROKE}" stroke-width="2.2"><circle cx="{l}" cy="{y}" r="6.5"/><circle cx="{r}" cy="{y}" r="6.5"/><line x1="{}" y1="{y}" x2="{}" y2="{y}" stroke-width="1.6"/></g>"#,
            l + 6.5,
            r - 6.5,
        ),
        Some("square" | "rect") => format!(
            r#"<g fill="none" stroke="{STROKE}" stroke-width="1.4"><rect x="{}" y="{}" width="14" height="10" rx="1.5" fill="rgba(255,255,255,0.15)"/><rect x="{}" y="{}" width="14" height="10" rx="1.5" fill="rgba(255,255,255,0.15)"/><line x1="{}" y1="{y}" x2="{}" y2="{y}"/></g>"#,
            l - 7.,
            y - 5.,
            r - 7.,
            y - 5.,
            l + 7.,
            r - 7.,
        ),
        Some("rect-thick") => format!(
            r#"<g fill="none" stroke="{STROKE}" stroke-width="2.2"><rect x="{}" y="{}" width="15" height="10" rx="1.5"/><rect x="{}" y="{}" width="15" height="10" rx="1.5"/><line x1="{}" y1="{y}" x2="{}" y2="{y}" stroke-width="1.6"/></g>"#,
            l - 7.5,
            y - 5.,
            r - 7.5,
            y - 5.,
            l + 7.5,
            r - 7.5,
        ),
        Some("square-thick") => format!(
            r#"<g fill="none" stroke="{STROKE}" stroke-width="2.4"><rect x="{}" y="{}" width="14" height="12" rx="1"/><rect x="{}" y="{}" width="14" height="12" rx="1"/><line x1="{}" y1="{y}" x2="{}" y2="{y}" stroke-width="1.6"/></g>"#,
            l - 7.,
            y - 6.,
            r - 7.,
            y - 6.,
            l + 7.,
            r - 7.,
        ),
        Some("sun") => format!(
            r#"<g><rect x="{}" y="{}" width="17" height="9" rx="1" fill="{STROKE}"/><rect x="{}" y="{}" width="17" height="9" rx="1" fill="{STROKE}"/><line x1="{}" y1="{}" x2="{}" y2="{}" stroke="{STROKE}" stroke-width="1.4"/><path d="M{},{} L{},{}" stroke="rgba(255,255,255,0.25)" stroke-width="0.8"/><path d="M{},{} L{},{}" stroke="rgba(255,255,255,0.25)" stroke-width="0.8"/></g>"#,
            l - 9.,
            y - 5.,
            r - 8.,
            y - 5.,
            l + 8.,
            y - 1.,
            r - 8.,
            y - 1.,
            l - 7.,
            y - 3.,
            l + 5.,
            y - 3.5,
            r - 7.,
            y - 3.,
            r + 5.,
            y - 3.5,
        ),
        _ => return,
    };
    s.push_str(&frame);
}

/// JavaScript's truthiness, which the web uses to tell a field is set.
fn truthy(v: Option<&Value>) -> bool {
    match v {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64() != Some(0.),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Array(_) | Value::Object(_)) => true,
    }
}

/// `p.key || fallback`. A set value that isn't text is printed as JavaScript would print a number
/// or boolean, which makes it an unknown shape or an invalid color, as on the web.
fn or<'a>(p: &'a Value, key: &str, fallback: &'a str) -> Cow<'a, str> {
    match p.get(key) {
        Some(Value::String(s)) if !s.is_empty() => Cow::Borrowed(s.as_str()),
        Some(v) if truthy(Some(v)) => Cow::Owned(v.to_string()),
        _ => Cow::Borrowed(fallback),
    }
}

/// `p.key === value`.
fn is(p: &Value, key: &str, value: &str) -> bool {
    p.get(key).and_then(Value::as_str) == Some(value)
}

fn find(table: &[(&str, &'static str)], key: &str) -> Option<&'static str> {
    table.iter().find(|(name, _)| *name == key).map(|(_, path)| *path)
}

/// Escapes text for an attribute value, as React does.
fn esc(s: &str) -> Cow<'_, str> {
    if !s.contains(['&', '<', '>', '"', '\'']) {
        return Cow::Borrowed(s);
    }
    let mut out = String::with_capacity(s.len() + 8);
    for c in s.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&#x27;"),
            c => out.push(c),
        }
    }
    Cow::Owned(out)
}

#[cfg(test)]
mod tests {
    // Not `super::*`: GPUI's own `test` macro would shadow the standard one.
    use super::{ACCENT, svg};
    use serde_json::{Value, json};

    /// Checks the markup is well-formed: every tag closes in order, attributes are quoted, and
    /// there's no stray text or bare `&`.
    fn well_formed(svg: &str) -> Result<(), String> {
        let mut open: Vec<&str> = Vec::new();
        let mut rest = svg;
        while let Some(start) = rest.find('<') {
            if !rest[..start].trim().is_empty() {
                return Err(format!("stray text {:?}", &rest[..start]));
            }
            let end = rest[start..].find('>').ok_or("unclosed tag")? + start;
            let tag = &rest[start + 1..end];
            rest = &rest[end + 1..];
            if let Some(name) = tag.strip_prefix('/') {
                if open.pop() != Some(name) {
                    return Err(format!("</{name}> closes the wrong tag"));
                }
                continue;
            }
            let (body, closed) = match tag.strip_suffix('/') {
                Some(body) => (body, true),
                None => (tag, false),
            };
            let name = body.split_whitespace().next().ok_or("empty tag")?;
            let mut attrs = body[name.len()..].trim();
            while !attrs.is_empty() {
                let eq = attrs.find("=\"").ok_or_else(|| format!("unquoted attribute in <{name}>"))?;
                let key = &attrs[..eq];
                if key.is_empty() || !key.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == ':') {
                    return Err(format!("bad attribute name {key:?}"));
                }
                let value_end = attrs[eq + 2..].find('"').ok_or("unterminated attribute")? + eq + 2;
                let value = &attrs[eq + 2..value_end];
                if value.contains('<') || value.split('&').skip(1).any(|e| !e.contains(';')) {
                    return Err(format!("unescaped value {value:?}"));
                }
                attrs = attrs[value_end + 1..].trim_start();
            }
            if !closed {
                open.push(name);
            }
        }
        if !rest.trim().is_empty() {
            return Err(format!("stray text {rest:?}"));
        }
        if !open.is_empty() {
            return Err(format!("unclosed {open:?}"));
        }
        Ok(())
    }

    #[test]
    fn draws_a_fixed_descriptor() {
        let p = json!({
            "cut": "bald-shine", "face": "square", "hair": "#112233", "skin": "#AABBCC", "beard": "full",
            "mouth": "smile", "eyes": "wide", "shirt": "tee-black", "brow": "arched", "glasses": "round",
            "moustache": true, "earring": true,
        });
        let out = svg(&p, "#123456");
        assert!(out.starts_with(r#"<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg""#));
        assert!(out.contains(
            r##"<path d="M50,30 L72,32 L74,72 L60,90 L40,90 L26,72 L28,32 Z" fill="#AABBCC" stroke="#1B1814" stroke-width="1"/>"##
        ));
        // Bald: no crown, only the shine's side piece and highlight.
        assert!(!out.contains(r##"fill="#112233" stroke="#1B1814" stroke-width="0.8""##));
        assert!(out.contains(
            r##"<path d="M50,24 C46,26 44,28 44,32 L48,30 Z" fill="#112233" stroke="#1B1814" stroke-width="0.6" opacity="0.95"/>"##
        ));
        assert!(out.contains(r#"<path d="M40,32 Q50,26 60,32" stroke="rgba(255,255,255,0.45)""#));
        assert!(out.contains(r##"<rect x="26" y="92" width="48" height="12" fill="#1F1B17"/>"##));
        // Round glasses hide the brows but not the eyes.
        assert!(!out.contains("<line x1=\"37\""));
        assert!(out.contains(r#"<circle cx="41" cy="58" r="2.6"/>"#));
        assert!(out.contains(r#"<circle cx="41" cy="58" r="6" fill="rgba(255,255,255,0.18)"/>"#));
        assert!(out.contains(r#"<line x1="47" y1="58" x2="53" y2="58"/>"#));
        assert!(out.contains(r#"<path d="M43,75 Q50,80 57,75" fill="none""#));
        assert!(out.contains(r##"<path d="M40,73 Q50,78 60,73 L58,75 Q50,77 42,75 Z" fill="#112233"/>"##));
        assert!(out.contains(r##"C44,80 32,80 28,66 Z" fill="#112233"/>"##));
        assert!(out.contains(r##"<circle cx="74" cy="66" r="1.6" fill="#123456"/>"##));
        assert!(
            out.contains(r##"<polygon points="50,4 92,28 92,72 50,96 8,72 8,28" fill="#123456" opacity="0.08"/>"##)
        );
        assert!(!out.contains(ACCENT));
    }

    #[test]
    fn sunglasses_keep_the_brows_and_hide_the_eyes() {
        let out = svg(&json!({"glasses": "sun", "brow": "arched", "beard": "full-grey"}), ACCENT);
        assert!(out.contains(r#"<line x1="37" y1="52" x2="45" y2="50.5"/><line x1="55" y1="50.5" x2="63" y2="52"/>"#));
        assert!(!out.contains(r#"r="2"/>"#));
        assert!(out.contains(r##"<rect x="32" y="53" width="17" height="9" rx="1" fill="#1B1814"/>"##));
        assert!(out.contains(r#"<path d="M34,55 L46,54.5" stroke="rgba(255,255,255,0.25)" stroke-width="0.8"/>"#));
        assert!(out.contains(r##"fill="#C8BEB0""##));
    }

    #[test]
    fn missing_fields_take_the_defaults() {
        let out = svg(&json!({}), ACCENT);
        // The neck in the default skin, as no shirt or collar covers it.
        assert!(out.contains(r##"<rect x="42" y="86" width="16" height="14" fill="#F1D6BA"/>"##));
        assert!(out.contains(r##"<path d="M50,28 C68,28 76,46 76,62 C76,80 64,90 50,90 C36,90 24,80 24,62 C24,46 32,28 50,28 Z" fill="#F1D6BA""##));
        assert!(out.contains(r##"<path d="M28,46 C28,32 38,22 50,22 C62,22 72,32 72,46 C70,42 64,38 58,38 C54,38 50,40 46,40 C42,40 38,42 30,46 Z" fill="#3B312A" stroke="#1B1814" stroke-width="0.8"/>"##));
        assert!(out.contains(r#"<line x1="37" y1="52" x2="45" y2="52"/><line x1="55" y1="52" x2="63" y2="52"/>"#));
        assert!(out.contains(r#"<circle cx="59" cy="58" r="2"/>"#));
        assert!(out.contains(r#"<path d="M44,76 L56,76" fill="none""#));
        assert!(out.contains(r##"fill="#BB7400" opacity="0.18"/>"##));
        for absent in ["rgba", "<rect x=\"26\"", "#C8BEB0", "<circle cx=\"74\""] {
            assert!(!out.contains(absent), "{absent} drawn without being asked for");
        }

        // Null, empty and false read as missing, and unknown names fall back, as in JavaScript.
        let unset = json!({
            "cut": "", "face": "blob", "hair": null, "skin": "", "mouth": "grin", "eyes": "narrow", "brow": null,
            "glasses": "", "moustache": false, "earring": 0, "leather": null, "beard": "", "shirt": "cape",
        });
        assert_eq!(svg(&unset, ACCENT), out);
        // A profile with no descriptor at all draws the same.
        assert_eq!(svg(&Value::Null, ACCENT), out);
    }

    #[test]
    fn every_option_is_well_formed() {
        let mut descriptors = vec![json!({}), json!({"skin": "\"><script>&", "hair": "a&b'c"})];
        for shirt in ["tee-black", "tee-grey", "shirt-tie", "shirt-blue", "shirt-aloha", "sweater-vee"] {
            descriptors.push(json!({"shirt": shirt}));
        }
        for glasses in ["round", "round-rimless", "round-thick", "square", "rect", "rect-thick", "square-thick", "sun"]
        {
            descriptors.push(json!({"glasses": glasses, "brow": "bushy"}));
        }
        for beard in ["goatee-stubble", "stubble", "full", "full-grey"] {
            descriptors.push(json!({"beard": beard, "moustache": true}));
        }
        for cut in super::HAIR_PATHS.iter().map(|(name, ..)| *name) {
            descriptors.push(json!({"cut": cut, "leather": true, "earring": 1}));
        }
        descriptors.extend([json!({"collar": "jabot"}), json!({"collar": "robe"}), json!({"neck": "turtleneck"})]);
        for p in &descriptors {
            let out = svg(p, ACCENT);
            if let Err(e) = well_formed(&out) {
                panic!("{p}: {e}\n{out}");
            }
        }
        assert!(well_formed("<svg><g></svg></g>").is_err());
        assert!(well_formed("<svg a=\"&\"/>").is_err());
    }
}
