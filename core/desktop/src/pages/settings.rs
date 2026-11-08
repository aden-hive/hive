//! Your profile, the rate limits colonies keep to on social platforms, the developer switches, and
//! which server the app talks to. Mirrors `frontend/src/components/SettingsModal.tsx`.

use std::path::PathBuf;
use std::sync::Arc;

use gpui_kit::assets::IconName;
use gpui_kit::base::{Disableable as _, h_flex, v_flex};
use gpui_kit::component::button::{Button, ButtonVariants as _};
use gpui_kit::component::input::{Input, InputState, NumberInput, Textarea, TextareaState};
use gpui_kit::component::spinner::Spinner;
use gpui_kit::component::switch::Switch;
use gpui_kit::component::{ActiveTheme as _, Icon, Sizable as _, StyledExt as _, Theme};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;
use serde_json::{Map, Value, json};

use super::text;
use crate::api::{FilePart, api};
use crate::{bg, ui};

/// The most the server takes for a picture (`MAX_AVATAR_BYTES` in `routes_config.py`).
const MAX_PICTURE_BYTES: u64 = 2 * 1024 * 1024;

/// The longest display name the web form takes.
const MAX_NAME_CHARS: usize = 120;

/// The windows a limit can be counted over, in the order they show.
const WINDOWS: [&str; 3] = ["hourly", "daily", "weekly"];

/// The developer switches: (feature key, title, what it does).
const SWITCHES: [(&str, &str, &str); 2] = [
    (
        "adaptive_tool_budget",
        "Adaptive worker budgets",
        "Colonies learn a tool-call budget from their successful workers and wind down strugglers early. Applies to running colonies too; a colony with its own setting keeps it.",
    ),
    (
        "stall_check",
        "Stall check",
        "When a queen ends a turn, a judge model checks whether she said she would do something, or agreed to a change you asked for, and stopped without doing it. If so, it reminds her once. Applies to running sessions.",
    ),
];

/// One window of one limit, e.g. LinkedIn invites per day.
struct LimitField {
    /// `<platform>.<action_type>.<window>`, as the server names it.
    key: String,
    window: &'static str,
    /// The value as loaded.
    saved: i64,
    /// The recommended most. Going above it is allowed, but puts the account at risk.
    ceiling: Option<i64>,
    field: Entity<InputState>,
}

struct Limit {
    platform: String,
    action: String,
    min_delay_s: f64,
    fields: Vec<LimitField>,
}

pub struct SettingsPage {
    /// The name and about as last loaded or saved.
    profile: Option<Result<(String, String), String>>,
    name: Entity<InputState>,
    about: Entity<TextareaState>,
    saving_profile: bool,
    /// What the last save said: a note when it saved, a problem when it didn't.
    profile_note: Option<Result<String, String>>,
    picture: Option<Arc<Image>>,
    uploading: bool,
    picture_error: Option<String>,
    limits: Option<Result<Vec<Limit>, String>>,
    saving_limits: bool,
    limits_error: Option<String>,
    /// What the server warned about on the last save.
    warnings: Vec<String>,
    features: Option<Result<Map<String, Value>, String>>,
    /// Whether a judge model is set; the stall check can't run without one.
    judge_set: Option<bool>,
    /// The switch being written, while it is.
    switching: Option<&'static str>,
    /// A switch that failed to change, and why.
    switch_error: Option<(&'static str, String)>,
    /// How many running colonies took the last budget change.
    applied: Option<i64>,
    health: Option<Result<Value, String>>,
    tasks: Vec<Task<()>>,
}

/// The picture's format and media type, told from its first bytes. The server takes only these two.
fn picture_kind(bytes: &[u8]) -> Option<(ImageFormat, &'static str)> {
    match bytes {
        [0x89, b'P', b'N', b'G', ..] => Some((ImageFormat::Png, "image/png")),
        [0xFF, 0xD8, ..] => Some((ImageFormat::Jpeg, "image/jpeg")),
        _ => None,
    }
}

/// What's wrong with a display name, if anything.
fn name_problem(name: &str) -> Option<String> {
    match name.trim().chars().count() {
        0 => Some("Your name can't be empty.".into()),
        n if n > MAX_NAME_CHARS => Some(format!("Your name is {n} characters long; the most is {MAX_NAME_CHARS}.")),
        _ => None,
    }
}

/// A limit as typed: a whole number, 1 or more.
fn parse_limit(typed: &str) -> Option<i64> {
    typed.trim().parse::<i64>().ok().filter(|n| *n >= 1)
}

/// "profile_view" → "Profile view".
fn capitalize(key: &str) -> String {
    let words = key.replace('_', " ");
    let mut chars = words.chars();
    chars.next().map(|c| c.to_uppercase().chain(chars).collect()).unwrap_or_default()
}

fn platform_label(platform: &str) -> String {
    match platform {
        "linkedin" => "LinkedIn".into(),
        "x" => "X (Twitter)".into(),
        other => capitalize(other),
    }
}

fn action_label(action: &str) -> String {
    match action {
        "dm" => "DM".into(),
        other => capitalize(other),
    }
}

fn window_label(window: &str) -> &'static str {
    match window {
        "hourly" => "Per hour",
        "daily" => "Per day",
        _ => "Per week",
    }
}

/// The windows a limit is counted over (those it has a default for), each with its value and
/// recommended most.
fn windows(entry: &Value) -> Vec<(&'static str, i64, Option<i64>)> {
    WINDOWS
        .into_iter()
        .filter_map(|w| {
            let default = entry[format!("{w}_default").as_str()].as_i64()?;
            Some((w, entry[w].as_i64().unwrap_or(default), entry[format!("{w}_max").as_str()].as_i64()))
        })
        .collect()
}

/// The server's health as one line, e.g. "Running · 4 sessions · 1 colony loaded".
fn health_line(health: &Value) -> String {
    let status = text(health, "status");
    let mut parts = vec![if status == "ok" { "Running".to_string() } else { capitalize(&status) }];
    if let Some(n) = health["sessions"].as_i64() {
        parts.push(format!("{n} {}", if n == 1 { "session" } else { "sessions" }));
    }
    if let Some(n) = health["agents_loaded"].as_i64() {
        parts.push(format!("{n} {} loaded", if n == 1 { "colony" } else { "colonies" }));
    }
    parts.join(" · ")
}

fn field_label(label: &'static str, theme: &Theme) -> Div {
    div().text_xs().font_medium().text_color(theme.muted_foreground).child(label)
}

impl SettingsPage {
    pub fn new(window: &mut Window, cx: &mut Context<Self>) -> Self {
        let name = cx.new(|cx| InputState::new(window, cx).placeholder("What your queens call you"));
        let about = cx.new(|cx| {
            TextareaState::new(window, cx).auto_grow(3, 8).placeholder("Your role, company, what you're working on")
        });
        cx.observe(&name, |_, _, cx| cx.notify()).detach();
        cx.observe(&about, |_, _, cx| cx.notify()).detach();
        let mut page = Self {
            profile: None,
            name,
            about,
            saving_profile: false,
            profile_note: None,
            picture: None,
            uploading: false,
            picture_error: None,
            limits: None,
            saving_limits: false,
            limits_error: None,
            warnings: Vec::new(),
            features: None,
            judge_set: None,
            switching: None,
            switch_error: None,
            applied: None,
            health: None,
            tasks: Vec::new(),
        };
        page.load(window, cx);
        page
    }

    fn load(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        self.load_profile(window, cx);
        self.load_limits(window, cx);
        self.load_features(cx);
        self.load_health(cx);
    }

    fn load_profile(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let api = api(cx);
        self.tasks.push(bg::spawn_in(
            window,
            cx,
            move || {
                let profile = api.get("/config/profile")?;
                // No picture is a 404; anything unreadable shows the initial too.
                let picture = api.bytes("/config/profile/avatar").ok().and_then(|bytes| {
                    let (format, _) = picture_kind(&bytes)?;
                    Some(Arc::new(Image::from_bytes(format, bytes)))
                });
                anyhow::Ok((profile, picture))
            },
            |this: &mut Self, loaded, window, cx| match loaded {
                Ok((profile, picture)) => {
                    this.show_profile(&profile, window, cx);
                    this.picture = picture;
                }
                Err(e) => this.profile = Some(Err(e.to_string())),
            },
        ));
    }

    /// Put the profile the server holds into the fields.
    fn show_profile(&mut self, profile: &Value, window: &mut Window, cx: &mut Context<Self>) {
        let (name, about) = (text(profile, "displayName"), text(profile, "about"));
        self.name.update(cx, |s, cx| s.set_value(name.clone(), window, cx));
        self.about.update(cx, |s, cx| s.set_value(about.clone(), window, cx));
        self.profile = Some(Ok((name, about)));
    }

    fn save_profile(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let name = self.name.read(cx).value().trim().to_string();
        let about = self.about.read(cx).value().trim().to_string();
        if let Some(problem) = name_problem(&name) {
            self.profile_note = Some(Err(problem));
            cx.notify();
            return;
        }
        self.saving_profile = true;
        self.profile_note = None;
        let api = api(cx);
        self.tasks.push(bg::spawn_in(
            window,
            cx,
            move || api.put("/config/profile", json!({ "displayName": name, "about": about })),
            |this: &mut Self, saved, window, cx| {
                this.saving_profile = false;
                match saved {
                    Ok(profile) => {
                        this.show_profile(&profile, window, cx);
                        this.profile_note = Some(Ok("Saved.".into()));
                    }
                    Err(e) => this.profile_note = Some(Err(format!("Couldn't save your profile: {e}"))),
                }
            },
        ));
        cx.notify();
    }

    fn choose_picture(&mut self, cx: &mut Context<Self>) {
        let paths = cx.prompt_for_paths(PathPromptOptions {
            files: true,
            directories: false,
            multiple: false,
            prompt: Some("Choose your picture".into()),
        });
        self.tasks.push(cx.spawn(async move |this, cx| {
            let Ok(Ok(Some(paths))) = paths.await else { return };
            let Some(path) = paths.into_iter().next() else { return };
            this.update(cx, |this, cx| this.upload_picture(path, cx)).ok();
        }));
    }

    fn upload_picture(&mut self, path: PathBuf, cx: &mut Context<Self>) {
        self.uploading = true;
        self.picture_error = None;
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || {
                let size = std::fs::metadata(&path)?.len();
                if size > MAX_PICTURE_BYTES {
                    anyhow::bail!("That picture is {:.1} MB; the most is 2 MB.", size as f64 / (1024.0 * 1024.0));
                }
                let bytes = std::fs::read(&path)?;
                let Some((format, content_type)) = picture_kind(&bytes) else {
                    anyhow::bail!("That file isn't a JPEG or PNG picture; only those two work.")
                };
                let filename =
                    path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_else(|| "avatar".into());
                api.post_multipart(
                    "/config/profile/avatar",
                    &[],
                    Some(FilePart {
                        field: "avatar".into(),
                        filename,
                        content_type: content_type.into(),
                        bytes: bytes.clone(),
                    }),
                )?;
                Ok(Arc::new(Image::from_bytes(format, bytes)))
            },
            |this: &mut Self, uploaded, _| {
                this.uploading = false;
                match uploaded {
                    Ok(picture) => this.picture = Some(picture),
                    Err(e) => this.picture_error = Some(format!("Couldn't change your picture: {e}")),
                }
            },
        ));
        cx.notify();
    }

    fn load_limits(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let api = api(cx);
        self.tasks.push(bg::spawn_in(
            window,
            cx,
            move || api.get("/config/rate-limits"),
            |this: &mut Self, loaded, window, cx| {
                this.limits =
                    Some(loaded.map(|body| Self::build_limits(&body["limits"], window, cx)).map_err(|e| e.to_string()));
            },
        ));
    }

    /// A field for each window of each limit, filled with its value.
    fn build_limits(rows: &Value, window: &mut Window, cx: &mut Context<Self>) -> Vec<Limit> {
        let mut limits = Vec::new();
        for row in rows.as_array().into_iter().flatten() {
            let (platform, action) = (text(row, "platform"), text(row, "action_type"));
            let mut fields = Vec::new();
            for (w, value, ceiling) in windows(row) {
                let field = cx.new(|cx| {
                    InputState::new(window, cx)
                        .validate(|typed, _| typed.len() <= 7 && typed.chars().all(|c| c.is_ascii_digit()))
                        .step(1.0)
                        .min(1.0)
                });
                field.update(cx, |s, cx| s.set_value(value.to_string(), window, cx));
                cx.observe(&field, |_, _, cx| cx.notify()).detach();
                fields.push(LimitField {
                    key: format!("{platform}.{action}.{w}"),
                    window: w,
                    saved: value,
                    ceiling,
                    field,
                });
            }
            limits.push(Limit { platform, action, min_delay_s: row["min_delay_s"].as_f64().unwrap_or(0.0), fields });
        }
        limits
    }

    /// The limits typed differently from the saved ones, by key; `None` when one isn't a number of 1 or more.
    fn limit_changes(&self, cx: &App) -> Option<Map<String, Value>> {
        let Some(Ok(limits)) = &self.limits else { return Some(Map::new()) };
        let mut changes = Map::new();
        for f in limits.iter().flat_map(|l| &l.fields) {
            let typed = parse_limit(&f.field.read(cx).value())?;
            if typed != f.saved {
                changes.insert(f.key.clone(), json!(typed));
            }
        }
        Some(changes)
    }

    fn save_limits(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let Some(changes) = self.limit_changes(cx) else {
            self.limits_error = Some("Each limit needs a whole number, 1 or more.".into());
            cx.notify();
            return;
        };
        if changes.is_empty() {
            return;
        }
        self.saving_limits = true;
        self.limits_error = None;
        self.warnings.clear();
        let api = api(cx);
        self.tasks.push(bg::spawn_in(
            window,
            cx,
            move || api.put("/config/rate-limits", json!({ "limits": changes })),
            |this: &mut Self, saved, window, cx| {
                this.saving_limits = false;
                match saved {
                    Ok(body) => {
                        this.limits = Some(Ok(Self::build_limits(&body["limits"], window, cx)));
                        this.warnings = body["warnings"]
                            .as_array()
                            .into_iter()
                            .flatten()
                            .filter_map(Value::as_str)
                            .map(str::to_string)
                            .collect();
                    }
                    Err(e) => this.limits_error = Some(format!("Couldn't save the limits: {e}")),
                }
            },
        ));
        cx.notify();
    }

    fn reset_limits(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if let Some(Ok(limits)) = &self.limits {
            for f in limits.iter().flat_map(|l| &l.fields) {
                f.field.update(cx, |s, cx| s.set_value(f.saved.to_string(), window, cx));
            }
        }
        self.limits_error = None;
        cx.notify();
    }

    fn load_features(&mut self, cx: &mut Context<Self>) {
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || {
                let features = api.get("/config/features");
                // A failed look counts as no judge, as on the web.
                let judge = api.get("/config/llm-sections").is_ok_and(|s| !s["judge"].is_null());
                anyhow::Ok((features, judge))
            },
            |this: &mut Self, loaded, _| {
                let Ok((features, judge)) = loaded else { return };
                this.features = Some(
                    features.map(|b| b["features"].as_object().cloned().unwrap_or_default()).map_err(|e| e.to_string()),
                );
                this.judge_set = Some(judge);
            },
        ));
    }

    fn set_feature(&mut self, key: &'static str, on: bool, cx: &mut Context<Self>) {
        let Some(Ok(features)) = self.features.as_mut() else { return };
        // Shown at once, and put back if the server says no.
        features.insert(key.into(), Value::Bool(on));
        self.switching = Some(key);
        self.switch_error = None;
        self.applied = None;
        let mut change = Map::new();
        change.insert(key.into(), Value::Bool(on));
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || api.put("/config/features", json!({ "features": change })),
            move |this: &mut Self, done, _| {
                this.switching = None;
                match done {
                    Ok(reply) => {
                        this.applied = reply["colonies_applied"].as_i64().filter(|_| key == "adaptive_tool_budget")
                    }
                    Err(e) => {
                        if let Some(Ok(features)) = this.features.as_mut() {
                            features.insert(key.into(), Value::Bool(!on));
                        }
                        this.switch_error = Some((key, format!("Couldn't change it: {e}")));
                    }
                }
            },
        ));
        cx.notify();
    }

    fn load_health(&mut self, cx: &mut Context<Self>) {
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || api.get("/health"),
            |this: &mut Self, health, _| this.health = Some(health.map_err(|e| e.to_string())),
        ));
    }

    fn render_profile(&self, cx: &mut Context<Self>) -> AnyElement {
        let change = Button::new("picture")
            .small()
            .ghost()
            .icon(IconName::Camera)
            .label("Change")
            .tooltip("Change your picture (JPEG or PNG, up to 2 MB)")
            .loading(self.uploading)
            .on_click(cx.listener(|this, _, _, cx| this.choose_picture(cx)));
        let saved = match &self.profile {
            None => return Spinner::new().into_any_element(),
            Some(Err(e)) => {
                return ui::error_line(format!("Couldn't load your profile: {e}"), cx.theme()).into_any_element();
            }
            Some(Ok(saved)) => saved.clone(),
        };
        let name = self.name.read(cx).value().trim().to_string();
        let dirty = name != saved.0 || self.about.read(cx).value().trim() != saved.1;
        let save = Button::new("save-profile")
            .small()
            .primary()
            .label("Save")
            .loading(self.saving_profile)
            .disabled(!dirty)
            .on_click(cx.listener(|this, _, window, cx| this.save_profile(window, cx)));
        let theme = cx.theme().clone();
        let picture = match &self.picture {
            Some(image) => img(image.clone())
                .size(px(72.))
                .flex_shrink_0()
                .rounded_full()
                .object_fit(ObjectFit::Cover)
                .into_any_element(),
            None => ui::initial_avatar(if name.is_empty() { "?" } else { &name }, px(72.), &theme).into_any_element(),
        };
        let note = match self.profile_note.clone() {
            Some(Ok(note)) if !dirty => div().text_sm().text_color(theme.success).child(note),
            Some(Err(problem)) => ui::error_line(problem, &theme),
            _ => div(),
        };
        v_flex()
            .gap_3()
            .p_4()
            .rounded_lg()
            .border_1()
            .border_color(theme.border)
            .child(
                h_flex()
                    .gap_5()
                    .items_start()
                    .child(v_flex().gap_2().items_center().child(picture).child(change))
                    .child(
                        v_flex()
                            .flex_1()
                            .min_w_0()
                            .gap_3()
                            .child(
                                v_flex()
                                    .gap_1()
                                    .child(field_label("Display name", &theme))
                                    .child(Input::new(&self.name).small()),
                            )
                            .child(
                                v_flex()
                                    .gap_1()
                                    .child(field_label("About · your queens remember this", &theme))
                                    .child(Textarea::new(&self.about)),
                            ),
                    ),
            )
            .when_some(self.picture_error.clone(), |col, e| col.child(ui::error_line(e, &theme)))
            .child(h_flex().justify_between().gap_2().child(note).child(save))
            .into_any_element()
    }

    fn render_limit(&self, limit: &Limit, theme: &Theme, cx: &App) -> Div {
        let mut over = false;
        let windows: Vec<Div> = limit
            .fields
            .iter()
            .map(|f| {
                let above = matches!((parse_limit(&f.field.read(cx).value()), f.ceiling), (Some(v), Some(c)) if v > c);
                over |= above;
                h_flex()
                    .gap_1p5()
                    .text_xs()
                    .child(div().text_color(theme.muted_foreground).child(window_label(f.window)))
                    .child(
                        div()
                            .w(px(112.))
                            .child(NumberInput::new(&f.field).small().when(above, |n| n.border_color(theme.warning))),
                    )
                    .child(
                        div()
                            .text_color(if above { theme.warning } else { theme.muted_foreground })
                            .child(format!("/ {}", f.ceiling.map_or("—".to_string(), |c| c.to_string()))),
                    )
            })
            .collect();
        v_flex()
            .gap_1()
            .child(
                ui::card(theme)
                    .justify_between()
                    .child(
                        v_flex()
                            .min_w_0()
                            .child(div().text_sm().font_medium().child(action_label(&limit.action)))
                            .when(limit.min_delay_s > 0.0, |col| {
                                col.child(
                                    div()
                                        .text_xs()
                                        .text_color(theme.muted_foreground)
                                        .child(format!("At least {} s apart", limit.min_delay_s)),
                                )
                            }),
                    )
                    .child(h_flex().gap_4().children(windows)),
            )
            .when(over, |col| {
                col.child(
                    h_flex()
                        .gap_1()
                        .px_1()
                        .text_xs()
                        .text_color(theme.warning)
                        .child(Icon::new(IconName::CircleAlert).xsmall())
                        .child("Above the recommended most, the account is more likely to be restricted or banned."),
                )
            })
    }

    fn render_limits(&self, cx: &mut Context<Self>) -> AnyElement {
        let limits = match &self.limits {
            None => return Spinner::new().into_any_element(),
            Some(Err(e)) => {
                return ui::error_line(format!("Couldn't load the rate limits: {e}"), cx.theme()).into_any_element();
            }
            Some(Ok(limits)) => limits,
        };
        let dirty = !matches!(self.limit_changes(cx), Some(c) if c.is_empty());
        let reset = Button::new("reset-limits")
            .small()
            .ghost()
            .label("Reset")
            .on_click(cx.listener(|this, _, window, cx| this.reset_limits(window, cx)));
        let save = Button::new("save-limits")
            .small()
            .primary()
            .label("Save")
            .loading(self.saving_limits)
            .on_click(cx.listener(|this, _, window, cx| this.save_limits(window, cx)));
        let theme = cx.theme().clone();
        // Grouped by platform, in the order the server lists them.
        let mut platforms: Vec<(&str, Vec<&Limit>)> = Vec::new();
        for limit in limits {
            match platforms.iter_mut().find(|(p, _)| *p == limit.platform) {
                Some((_, group)) => group.push(limit),
                None => platforms.push((&limit.platform, vec![limit])),
            }
        }
        let groups: Vec<Div> = platforms
            .into_iter()
            .map(|(platform, group)| {
                v_flex()
                    .gap_2()
                    .child(div().text_sm().font_semibold().child(platform_label(platform)))
                    .children(group.into_iter().map(|limit| self.render_limit(limit, &theme, cx)))
            })
            .collect();
        v_flex()
            .gap_4()
            .child(ui::muted("How many actions colonies may take on each platform. The number after the slash is the recommended most.", &theme))
            .children(groups)
            .when_some(self.limits_error.clone(), |col, e| col.child(ui::error_line(e, &theme)))
            .when(dirty, |col| col.child(h_flex().gap_2().justify_end().child(reset).child(save)))
            .when(!self.warnings.is_empty(), |col| {
                col.child(
                    v_flex()
                        .gap_1()
                        .px_3()
                        .py_2()
                        .rounded_md()
                        .border_1()
                        .border_color(theme.warning)
                        .text_xs()
                        .child(h_flex().gap_2().font_medium().text_color(theme.warning).child(Icon::new(IconName::CircleAlert).xsmall()).child("Saved, with values above the recommended most"))
                        .children(self.warnings.iter().map(|w| div().child(w.clone()))),
                )
            })
            .into_any_element()
    }

    fn render_developer(&self, cx: &mut Context<Self>) -> AnyElement {
        let features = match &self.features {
            None => return Spinner::new().into_any_element(),
            Some(Err(e)) => {
                return ui::error_line(format!("Couldn't load the switches: {e}"), cx.theme()).into_any_element();
            }
            Some(Ok(features)) => features.clone(),
        };
        let mut rows = Vec::new();
        for (key, title, about) in SWITCHES {
            let on = features.get(key).and_then(Value::as_bool).unwrap_or(false);
            let stall = key == "stall_check";
            // Turning the stall check off never needs a judge.
            let blocked = stall && self.judge_set != Some(true) && !on;
            let switch = Switch::new(key)
                .checked(on)
                .disabled(blocked || self.switching == Some(key))
                .on_click(cx.listener(move |this, checked: &bool, _, cx| this.set_feature(key, *checked, cx)));
            let error = self.switch_error.as_ref().filter(|(k, _)| *k == key).map(|(_, e)| e.clone());
            let applied = self.applied.filter(|n| *n > 0 && key == "adaptive_tool_budget");
            let theme = cx.theme();
            rows.push(
                ui::card(theme)
                    .justify_between()
                    .child(
                        v_flex()
                            .min_w_0()
                            .flex_1()
                            .gap_0p5()
                            .child(div().text_sm().font_medium().child(title))
                            .child(div().text_xs().text_color(theme.muted_foreground).child(about))
                            .when(stall && self.judge_set == Some(false), |col| {
                                col.child(
                                    div()
                                        .text_xs()
                                        .text_color(theme.warning)
                                        .child("Needs a judge model. Set one under Judge on the Models page."),
                                )
                            })
                            .when_some(applied, |col, n| {
                                col.child(div().text_xs().text_color(theme.success).child(format!(
                                    "Applied to {n} running {}.",
                                    if n == 1 { "colony" } else { "colonies" }
                                )))
                            })
                            .when_some(error, |col, e| col.child(ui::error_line(e, theme))),
                    )
                    .child(switch),
            );
        }
        v_flex().gap_2().children(rows).into_any_element()
    }

    fn render_about(&self, cx: &mut Context<Self>) -> AnyElement {
        let check =
            Button::new("check-health").small().ghost().icon(IconName::RefreshCw).tooltip("Check again").on_click(
                cx.listener(|this, _, _, cx| {
                    this.health = None;
                    this.load_health(cx);
                    cx.notify();
                }),
            );
        let base = api(cx).base().to_string();
        let theme = cx.theme().clone();
        let (color, status) = match &self.health {
            None => (theme.muted_foreground, "Checking…".to_string()),
            Some(Ok(health)) if text(health, "status") == "ok" => (theme.success, health_line(health)),
            Some(Ok(health)) => (theme.warning, health_line(health)),
            Some(Err(e)) => (theme.danger, format!("Not answering: {e}")),
        };
        v_flex()
            .gap_2()
            .child(
                ui::card(&theme)
                    .justify_between()
                    .child(
                        v_flex().min_w_0().child(div().text_sm().font_medium().child("Server")).child(
                            div()
                                .text_xs()
                                .font_family(theme.mono_font_family.clone())
                                .text_color(theme.muted_foreground)
                                .child(base),
                        ),
                    )
                    .child(
                        h_flex()
                            .gap_2()
                            .child(ui::dot(color))
                            .child(div().text_sm().text_color(color).child(status))
                            .child(check),
                    ),
            )
            .child(ui::muted(format!("Hive desktop {}", env!("CARGO_PKG_VERSION")), &theme))
            .into_any_element()
    }
}

impl Render for SettingsPage {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let theme = cx.theme().clone();
        let (header, body) =
            ui::page("settings-body", "Settings", "Your profile, rate limits and developer switches.", &theme);
        let header = header.child(
            h_flex().pt_2().child(
                Button::new("refresh")
                    .small()
                    .ghost()
                    .icon(IconName::RefreshCw)
                    .label("Refresh")
                    .on_click(cx.listener(|this, _, window, cx| this.load(window, cx))),
            ),
        );
        let content = v_flex()
            .gap_8()
            .px_8()
            .py_6()
            .w_full()
            .max_w(px(880.))
            .mx_auto()
            .child(ui::section("Profile", &theme).child(self.render_profile(cx)))
            .child(ui::section("Rate limits", &theme).child(self.render_limits(cx)))
            .child(ui::section("Developer", &theme).child(self.render_developer(cx)))
            .child(ui::section("About", &theme).child(self.render_about(cx)));
        v_flex().size_full().child(header).child(body.child(content))
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::{
        action_label, capitalize, health_line, name_problem, parse_limit, picture_kind, platform_label, windows,
    };

    #[test]
    fn picture_kind_takes_only_jpeg_and_png() {
        assert_eq!(picture_kind(&[0x89, b'P', b'N', b'G', 0x0D, 0x0A]).map(|(_, t)| t), Some("image/png"));
        assert_eq!(picture_kind(&[0xFF, 0xD8, 0xFF, 0xE0]).map(|(_, t)| t), Some("image/jpeg"));
        assert!(picture_kind(b"RIFF\0\0\0\0WEBPVP8 ").is_none());
        assert!(picture_kind(b"GIF89a").is_none());
        assert!(picture_kind(&[]).is_none());
    }

    #[test]
    fn name_problem_wants_1_to_120_characters() {
        assert!(name_problem("Ava").is_none());
        assert!(name_problem("   ").is_some());
        assert!(name_problem(&"é".repeat(120)).is_none());
        assert!(name_problem(&"m".repeat(121)).is_some());
    }

    #[test]
    fn parse_limit_wants_a_whole_number_of_at_least_one() {
        assert_eq!(parse_limit(" 25 "), Some(25));
        assert_eq!(parse_limit("1"), Some(1));
        assert_eq!(parse_limit("0"), None);
        assert_eq!(parse_limit(""), None);
        assert_eq!(parse_limit("2.5"), None);
    }

    #[test]
    fn windows_are_those_with_a_default() {
        let entry = json!({"platform": "x", "action_type": "dm", "hourly": 12, "hourly_max": 80, "hourly_default": 20, "daily_max": 200, "daily_default": 60});
        assert_eq!(windows(&entry), vec![("hourly", 12, Some(80)), ("daily", 60, Some(200))]);
    }

    #[test]
    fn labels_read_as_words() {
        assert_eq!(capitalize("profile_view"), "Profile view");
        assert_eq!(action_label("dm"), "DM");
        assert_eq!(platform_label("linkedin"), "LinkedIn");
        assert_eq!(platform_label("x"), "X (Twitter)");
        assert_eq!(platform_label("instagram"), "Instagram");
    }

    #[test]
    fn health_line_counts_sessions_and_colonies() {
        assert_eq!(
            health_line(&json!({"status": "ok", "sessions": 1, "agents_loaded": 0})),
            "Running · 1 session · 0 colonies loaded"
        );
        assert_eq!(
            health_line(&json!({"status": "degraded", "sessions": 4, "agents_loaded": 1})),
            "Degraded · 4 sessions · 1 colony loaded"
        );
    }
}
