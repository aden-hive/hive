//! A queen's profile: who she is (her persona and the pillars beneath it), her soul, the model she
//! thinks with, what she remembers and what she can do, read and set on one page. Mirrors
//! `frontend/src/pages/queen-profile.tsx`.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use gpui_kit::assets::IconName;
use gpui_kit::base::{Disableable as _, Selectable as _, h_flex, v_flex};
use gpui_kit::component::button::{Button, ButtonVariants as _};
use gpui_kit::component::input::{Input, InputState, Position, Textarea, TextareaState};
use gpui_kit::component::spinner::Spinner;
use gpui_kit::component::{ActiveTheme as _, Icon, Sizable as _, StyledExt as _, Theme};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;
use serde_json::{Value, json};

use super::{flag, text};
use crate::api::{FilePart, api};
use crate::shell::{Page, Route, Shell};
use crate::{bg, ui};

/// The most the server takes for a picture (`MAX_AVATAR_BYTES` in `routes_queens.py`).
const MAX_PICTURE_BYTES: usize = 2 * 1024 * 1024;

/// The pillars that are maps of text: (key, title, what it holds, the fields her prompt reads).
/// Fields she has beyond these are kept and shown too.
const PILLARS: [(&str, &str, &str, &[&str]); 3] = [
    (
        "hidden_background",
        "Hidden background",
        "Moves her, and is never shown to anyone",
        &["past_wound", "deep_motive", "behavioral_mapping"],
    ),
    (
        "psychological_profile",
        "Psychological profile",
        "The masks she wears, and what she is not",
        &["social_masks", "anti_stereotype"],
    ),
    ("world_lore", "World lore", "Where she lives, and the words she uses", &["habitat", "lexicon"]),
];

/// Where on the page a write belongs, so its spinner and its error show beside it.
#[derive(Clone, Copy, PartialEq)]
enum Part {
    Identity,
    Picture,
    Persona,
    Pillars,
    Craft,
    Model,
    Soul,
}

/// The one thing open for editing.
enum Editor {
    Identity {
        name: Entity<InputState>,
        title: Entity<InputState>,
    },
    Traits(Entity<TextareaState>),
    Skills(Entity<TextareaState>),
    Pillar {
        key: &'static str,
        fields: Vec<(String, Entity<TextareaState>)>,
    },
    /// Rows of "when this happens" and "she does that".
    Triggers(Vec<(Entity<InputState>, Entity<TextareaState>)>),
}

/// A destructive action clicked once, waiting for the second click.
#[derive(Clone, PartialEq)]
enum Confirm {
    RemovePicture,
    Dismiss,
    Restore(i64),
}

/// A model picker row: label, a note such as the context size, and what picking it does (`None` for a
/// row that only says something, like "Loading…").
type PickerRow = (String, String, Option<Choice>);

#[derive(Clone)]
enum Choice {
    Endpoint { endpoint: String, model: String },
    Catalog { provider: String, model: String },
}

pub struct ProfilePage {
    queen_id: String,
    shell: WeakEntity<Shell>,
    persona: Option<Result<Value, String>>,
    overview: Option<Value>,
    picture: Option<Arc<Image>>,
    soul: Option<Result<Value, String>>,
    models: Option<Result<Value, String>>,
    /// A running endpoint's models, fetched when the picker first needs them.
    endpoint_models: HashMap<String, Result<Vec<Value>, String>>,
    /// The model search, while the picker is open.
    picker: Option<Entity<InputState>>,
    editor: Option<Editor>,
    busy: Option<Part>,
    error: Option<(Part, String)>,
    confirm: Option<Confirm>,
    show_history: bool,
    soul_load: Option<Task<()>>,
    /// The next look at her soul, while she reflects.
    soul_poll: Option<Task<()>>,
    tasks: Vec<Task<()>>,
}

fn label(key: &str) -> String {
    let words = key.replace('_', " ");
    let mut chars = words.chars();
    chars.next().map(|c| c.to_uppercase().chain(chars).collect()).unwrap_or_default()
}

fn as_text(value: &Value) -> String {
    match value {
        Value::String(s) => s.clone(),
        Value::Null => String::new(),
        other => other.to_string(),
    }
}

/// Her skills (free text) as items: split at commas and list marks outside brackets, so
/// "drawing (ink, watercolor), teasing" is two skills. As `queen-profile/skills.ts` does.
fn split_skills(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut depth = 0usize;
    let mut current = String::new();
    for ch in text.chars() {
        if "(（[【".contains(ch) {
            depth += 1;
        } else if ")）]】".contains(ch) {
            depth = depth.saturating_sub(1);
        }
        if depth == 0 && ",，、;；\n".contains(ch) {
            if !current.trim().is_empty() {
                out.push(current.trim().to_string());
            }
            current.clear();
        } else {
            current.push(ch);
        }
    }
    if !current.trim().is_empty() {
        out.push(current.trim().to_string());
    }
    out
}

/// The picture's format and media type, told from its first bytes. The server takes only these two.
fn picture_kind(bytes: &[u8]) -> Option<(ImageFormat, &'static str)> {
    match bytes {
        [0x89, b'P', b'N', b'G', ..] => Some((ImageFormat::Png, "image/png")),
        [0xFF, 0xD8, ..] => Some((ImageFormat::Jpeg, "image/jpeg")),
        _ => None,
    }
}

fn context_label(tokens: Option<i64>) -> Option<String> {
    match tokens? {
        t if t >= 1_000_000 => Some(format!("{}M", (t as f64 / 100_000.0).round() / 10.0)),
        t if t > 0 => Some(format!("{}k", (t as f64 / 1000.0).round() as i64)),
        _ => None,
    }
}

/// "model · where it comes from", as the Models page summarises a slot.
fn model_summary(slot: &Value) -> String {
    let source = match text(slot, "source").as_str() {
        "endpoint" => text(slot, "endpoint"),
        "subscription" => text(slot, "subscription"),
        _ => text(slot, "provider"),
    };
    [text(slot, "model"), source].into_iter().filter(|s| !s.is_empty()).collect::<Vec<_>>().join(" · ")
}

/// The end of `text`, where the cursor goes when an editor opens: the column is clamped to the line.
fn end_of(text: &str) -> Position {
    Position { line: text.matches('\n').count() as u32, character: u32::MAX }
}

/// An ISO time as "YYYY-MM-DD HH:MM".
fn when(iso: &str) -> String {
    iso.chars().take(16).collect::<String>().replace('T', " ")
}

impl ProfilePage {
    pub fn new(queen_id: String, shell: WeakEntity<Shell>, _window: &mut Window, cx: &mut Context<Self>) -> Self {
        let mut page = Self {
            queen_id,
            shell,
            persona: None,
            overview: None,
            picture: None,
            soul: None,
            models: None,
            endpoint_models: HashMap::new(),
            picker: None,
            editor: None,
            busy: None,
            error: None,
            confirm: None,
            show_history: false,
            soul_load: None,
            soul_poll: None,
            tasks: Vec::new(),
        };
        page.load(cx);
        page
    }

    fn load(&mut self, cx: &mut Context<Self>) {
        let api = api(cx);
        let id = self.queen_id.clone();
        self.tasks.push(bg::spawn(
            cx,
            move || {
                let persona = api.get(&format!("/queen/{id}/persona"));
                let overview = api.get(&format!("/queen/{id}/overview")).ok();
                // No picture is a 404; anything unreadable shows her initial too.
                let picture = api.bytes(&format!("/queen/{id}/avatar")).ok().and_then(|bytes| {
                    let (format, _) = picture_kind(&bytes)?;
                    Some(Arc::new(Image::from_bytes(format, bytes)))
                });
                anyhow::Ok((persona, overview, picture))
            },
            |this: &mut Self, loaded, _| {
                let Ok((persona, overview, picture)) = loaded else { return };
                this.persona = Some(match persona {
                    Ok(body) => Ok(body["persona"].clone()),
                    Err(e) if e.to_string().starts_with("HTTP 404") => Err("There is no queen by this id.".into()),
                    Err(e) => Err(format!("Couldn't load her profile: {e}")),
                });
                this.overview = overview;
                this.picture = picture;
            },
        ));
        self.load_soul(cx);
        self.load_models(cx);
    }

    fn load_soul(&mut self, cx: &mut Context<Self>) {
        let api = api(cx);
        let path = format!("/queen/{}/soul", self.queen_id);
        self.soul_load = Some(bg::spawn(
            cx,
            move || api.get(&path),
            |this: &mut Self, soul, cx| this.show_soul(soul.map_err(|e| e.to_string()), cx),
        ));
    }

    fn show_soul(&mut self, soul: Result<Value, String>, cx: &mut Context<Self>) {
        let reflecting = soul.as_ref().is_ok_and(|s| flag(s, "reflecting") || flag(s, "probing"));
        self.soul = Some(soul);
        self.soul_poll = reflecting.then(|| {
            cx.spawn(async move |this, cx| {
                cx.background_executor().timer(Duration::from_secs(3)).await;
                this.update(cx, |this, cx| this.load_soul(cx)).ok();
            })
        });
    }

    fn load_models(&mut self, cx: &mut Context<Self>) {
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || api.get("/models/overview"),
            |this: &mut Self, models, _| this.models = Some(models.map_err(|e| e.to_string())),
        ));
    }

    fn persona_value(&self) -> Value {
        match &self.persona {
            Some(Ok(p)) => p.clone(),
            _ => Value::Null,
        }
    }

    /// Tell the sidebar she changed. A rename also drops her cached chat, which was built with the old name.
    fn refresh_shell(&self, renamed: bool, window: &mut Window, cx: &mut Context<Self>) {
        let id = self.queen_id.clone();
        self.shell
            .update(cx, |shell, cx| {
                if renamed {
                    shell.forget(&Route::Queen(id));
                }
                shell.refresh_queens(window, cx);
            })
            .ok();
    }

    fn go(&self, route: Route, window: &mut Window, cx: &mut Context<Self>) {
        self.shell.update(cx, |shell, cx| shell.go(route, window, cx)).ok();
    }

    /// True on the second click of a destructive action; the first only arms it.
    fn confirmed(&mut self, what: Confirm, cx: &mut Context<Self>) -> bool {
        if self.confirm.as_ref() == Some(&what) {
            self.confirm = None;
            return true;
        }
        self.confirm = Some(what);
        cx.notify();
        false
    }

    /// Replace these persona fields whole; `null` removes a pillar.
    fn save_persona(
        &mut self,
        part: Part,
        fields: serde_json::Map<String, Value>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let renamed = fields.contains_key("name");
        self.busy = Some(part);
        self.error = None;
        let api = api(cx);
        let path = format!("/queen/{}/persona", self.queen_id);
        self.tasks.push(bg::spawn_in(
            window,
            cx,
            move || api.put(&path, json!({ "persona": fields })),
            move |this: &mut Self, saved, window, cx| {
                this.busy = None;
                match saved {
                    Ok(body) => {
                        this.persona = Some(Ok(body["persona"].clone()));
                        this.editor = None;
                        if renamed {
                            this.refresh_shell(true, window, cx);
                        }
                    }
                    Err(e) => this.error = Some((part, e.to_string())),
                }
            },
        ));
        cx.notify();
    }

    fn open_editor(&mut self, editor: Editor, cx: &mut Context<Self>) {
        self.editor = Some(editor);
        self.error = None;
        cx.notify();
    }

    fn close_editor(&mut self, cx: &mut Context<Self>) {
        self.editor = None;
        self.error = None;
        cx.notify();
    }

    fn textarea(
        value: String,
        min: usize,
        max: usize,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> Entity<TextareaState> {
        cx.new(|cx| TextareaState::new(window, cx).auto_grow(min, max).default_value(value))
    }

    fn edit_identity(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let persona = self.persona_value();
        let field = |value: String, placeholder: &'static str, window: &mut Window, cx: &mut Context<Self>| {
            cx.new(|cx| InputState::new(window, cx).placeholder(placeholder).default_value(value))
        };
        let name = field(text(&persona, "name"), "Her name", window, cx);
        let title = field(text(&persona, "title"), "Her title, e.g. Head of Testing", window, cx);
        // Save is offered only while both are filled in, so typing redraws the page.
        cx.observe(&name, |_, _, cx| cx.notify()).detach();
        cx.observe(&title, |_, _, cx| cx.notify()).detach();
        name.update(cx, |s, cx| s.set_cursor_position(end_of(&s.value()), window, cx));
        self.open_editor(Editor::Identity { name, title }, cx);
    }

    fn save_identity(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let Some(Editor::Identity { name, title }) = &self.editor else { return };
        let name = name.read(cx).value().trim().to_string();
        let title = title.read(cx).value().trim().to_string();
        if name.is_empty() || title.is_empty() {
            return;
        }
        let mut fields = serde_json::Map::new();
        fields.insert("name".into(), json!(name));
        fields.insert("title".into(), json!(title));
        self.save_persona(Part::Identity, fields, window, cx);
    }

    fn save_text(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let (part, key, value) = match &self.editor {
            Some(Editor::Traits(field)) => (Part::Persona, "core_traits", field.read(cx).value().to_string()),
            Some(Editor::Skills(field)) => (Part::Craft, "skills", field.read(cx).value().trim().to_string()),
            _ => return,
        };
        let mut fields = serde_json::Map::new();
        fields.insert(key.into(), json!(value));
        self.save_persona(part, fields, window, cx);
    }

    fn edit_pillar(&mut self, key: &'static str, window: &mut Window, cx: &mut Context<Self>) {
        let current = self.persona_value()[key].as_object().cloned().unwrap_or_default();
        let known: &[&str] = PILLARS.iter().find(|p| p.0 == key).map(|p| p.3).unwrap_or(&[]);
        let mut keys: Vec<String> = known.iter().map(|k| k.to_string()).collect();
        keys.extend(current.keys().filter(|k| !known.contains(&k.as_str())).cloned());
        let fields = keys
            .into_iter()
            .map(|k| {
                let value = current.get(&k).map(as_text).unwrap_or_default();
                (k, Self::textarea(value, 2, 12, window, cx))
            })
            .collect();
        self.open_editor(Editor::Pillar { key, fields }, cx);
    }

    fn trigger_row(
        trigger: String,
        reaction: String,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> (Entity<InputState>, Entity<TextareaState>) {
        let when = cx.new(|cx| InputState::new(window, cx).placeholder("When…").default_value(trigger));
        (when, Self::textarea(reaction, 2, 8, window, cx))
    }

    fn edit_triggers(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let current = self.persona_value()["behavior_triggers"].as_array().cloned().unwrap_or_default();
        let mut rows: Vec<_> =
            current.iter().map(|t| Self::trigger_row(text(t, "trigger"), text(t, "reaction"), window, cx)).collect();
        if rows.is_empty() {
            rows.push(Self::trigger_row(String::new(), String::new(), window, cx));
        }
        self.open_editor(Editor::Triggers(rows), cx);
    }

    fn save_pillar(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let (key, value) = match &self.editor {
            Some(Editor::Pillar { key, fields }) => {
                let kept: serde_json::Map<String, Value> = fields
                    .iter()
                    .filter_map(|(k, field)| {
                        let v = field.read(cx).value().trim().to_string();
                        (!v.is_empty()).then(|| (k.clone(), Value::String(v)))
                    })
                    .collect();
                // Emptied out, the pillar goes rather than stay as a husk.
                (*key, if kept.is_empty() { Value::Null } else { Value::Object(kept) })
            }
            Some(Editor::Triggers(rows)) => {
                let kept: Vec<Value> = rows
                    .iter()
                    .map(|(when, then)| {
                        (when.read(cx).value().trim().to_string(), then.read(cx).value().trim().to_string())
                    })
                    .filter(|(when, then)| !when.is_empty() && !then.is_empty())
                    .map(|(trigger, reaction)| json!({ "trigger": trigger, "reaction": reaction }))
                    .collect();
                ("behavior_triggers", if kept.is_empty() { Value::Null } else { Value::Array(kept) })
            }
            _ => return,
        };
        let mut fields = serde_json::Map::new();
        fields.insert(key.into(), value);
        self.save_persona(Part::Pillars, fields, window, cx);
    }

    fn choose_picture(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        self.confirm = None;
        let paths = cx.prompt_for_paths(PathPromptOptions {
            files: true,
            directories: false,
            multiple: false,
            prompt: Some("Choose her picture".into()),
        });
        self.tasks.push(cx.spawn_in(window, async move |this, cx| {
            let Ok(Ok(Some(paths))) = paths.await else { return };
            let Some(path) = paths.into_iter().next() else { return };
            this.update_in(cx, |this, window, cx| this.upload_picture(path, window, cx)).ok();
        }));
    }

    fn upload_picture(&mut self, path: PathBuf, window: &mut Window, cx: &mut Context<Self>) {
        self.busy = Some(Part::Picture);
        self.error = None;
        let api = api(cx);
        let target = format!("/queen/{}/avatar", self.queen_id);
        self.tasks.push(bg::spawn_in(
            window,
            cx,
            move || {
                let bytes = std::fs::read(&path)?;
                let Some((format, content_type)) = picture_kind(&bytes) else {
                    anyhow::bail!("That file isn't a JPEG or PNG picture; only those two work.")
                };
                if bytes.len() > MAX_PICTURE_BYTES {
                    anyhow::bail!(
                        "That picture is {:.1} MB; the most is 2 MB.",
                        bytes.len() as f64 / (1024.0 * 1024.0)
                    );
                }
                let filename =
                    path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_else(|| "avatar".into());
                api.post_multipart(
                    &target,
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
            |this: &mut Self, uploaded, window, cx| {
                this.busy = None;
                match uploaded {
                    Ok(picture) => {
                        this.picture = Some(picture);
                        this.refresh_shell(false, window, cx);
                    }
                    Err(e) => this.error = Some((Part::Picture, e.to_string())),
                }
            },
        ));
        cx.notify();
    }

    fn remove_picture(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if !self.confirmed(Confirm::RemovePicture, cx) {
            return;
        }
        self.busy = Some(Part::Picture);
        self.error = None;
        let api = api(cx);
        let path = format!("/queen/{}/avatar", self.queen_id);
        self.tasks.push(bg::spawn_in(
            window,
            cx,
            move || api.delete(&path),
            |this: &mut Self, removed, window, cx| {
                this.busy = None;
                match removed {
                    Ok(_) => {
                        this.picture = None;
                        this.refresh_shell(false, window, cx);
                    }
                    Err(e) => this.error = Some((Part::Picture, e.to_string())),
                }
            },
        ));
        cx.notify();
    }

    fn open_picker(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        if self.picker.take().is_some() {
            cx.notify();
            return;
        }
        let search = cx.new(|cx| InputState::new(window, cx).placeholder("Search models"));
        cx.observe(&search, |_, _, cx| cx.notify()).detach();
        search.update(cx, |s, cx| s.focus(window, cx));
        self.picker = Some(search);
        // Endpoints answer live, so their lists are fetched when first needed.
        let running: Vec<String> = self
            .endpoints()
            .iter()
            .filter(|e| flag(e, "running"))
            .map(|e| text(e, "name"))
            .filter(|n| !self.endpoint_models.contains_key(n))
            .collect();
        for name in running {
            let api = api(cx);
            let key = name.clone();
            self.tasks.push(bg::spawn(
                cx,
                move || api.get(&format!("/models/endpoints/{name}/models")),
                move |this: &mut Self, models, _| {
                    let models =
                        models.map(|m| m["models"].as_array().cloned().unwrap_or_default()).map_err(|e| e.to_string());
                    this.endpoint_models.insert(key, models);
                },
            ));
        }
        cx.notify();
    }

    fn endpoints(&self) -> Vec<Value> {
        match &self.models {
            Some(Ok(o)) => o["endpoints"].as_array().cloned().unwrap_or_default(),
            _ => Vec::new(),
        }
    }

    /// Give her a model of her own, or (`None`) send her back to the main one.
    fn pick(&mut self, choice: Option<Choice>, cx: &mut Context<Self>) {
        self.busy = Some(Part::Model);
        self.error = None;
        let api = api(cx);
        let slot = format!("/models/slots/queen:{}", self.queen_id);
        self.tasks.push(bg::spawn(
            cx,
            move || match choice {
                None => api.delete(&slot),
                Some(Choice::Endpoint { endpoint, model }) => {
                    api.put(&slot, json!({ "source": "endpoint", "endpoint": endpoint, "model": model }))
                }
                Some(Choice::Catalog { provider, model }) => {
                    api.put(&slot, json!({ "source": "catalog", "provider": provider, "model": model }))
                }
            },
            |this: &mut Self, done, cx| {
                this.busy = None;
                match done {
                    Ok(_) => {
                        this.picker = None;
                        this.load_models(cx);
                    }
                    Err(e) => this.error = Some((Part::Model, e.to_string())),
                }
            },
        ));
        cx.notify();
    }

    /// Post to one of her soul's actions, then show her soul as it is after.
    fn soul_action(&mut self, action: String, body: Value, cx: &mut Context<Self>) {
        self.busy = Some(Part::Soul);
        self.error = None;
        let api = api(cx);
        let base = format!("/queen/{}/soul", self.queen_id);
        self.tasks.push(bg::spawn(
            cx,
            move || {
                api.post(&format!("{base}/{action}"), body)?;
                api.get(&base)
            },
            |this: &mut Self, done, cx| {
                this.busy = None;
                match done {
                    Ok(soul) => this.show_soul(Ok(soul), cx),
                    Err(e) => this.error = Some((Part::Soul, e.to_string())),
                }
            },
        ));
        cx.notify();
    }

    fn error_for(&self, part: Part, theme: &Theme) -> Option<Div> {
        self.error.as_ref().filter(|(p, _)| *p == part).map(|(_, e)| ui::error_line(e.clone(), theme))
    }

    /// Cancel and Save under an editor, with a hint on the left.
    fn edit_foot(
        &self,
        id: &'static str,
        part: Part,
        hint: &'static str,
        save: fn(&mut Self, &mut Window, &mut Context<Self>),
        cx: &mut Context<Self>,
    ) -> Div {
        let theme = cx.theme().clone();
        h_flex().justify_between().gap_2().child(div().text_xs().text_color(theme.muted_foreground).child(hint)).child(
            h_flex()
                .gap_2()
                .child(
                    Button::new(SharedString::from(format!("{id}-cancel")))
                        .small()
                        .ghost()
                        .label("Cancel")
                        .on_click(cx.listener(|this, _, _, cx| this.close_editor(cx))),
                )
                .child(
                    Button::new(SharedString::from(format!("{id}-save")))
                        .small()
                        .primary()
                        .icon(IconName::Check)
                        .label("Save")
                        .loading(self.busy == Some(part))
                        .on_click(cx.listener(move |this, _, window, cx| save(this, window, cx))),
                ),
        )
    }

    fn render_hero(&self, persona: &Value, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        let name = text(persona, "name");
        let title = text(persona, "title");
        let picture = match &self.picture {
            Some(image) => img(image.clone())
                .size(px(104.))
                .flex_shrink_0()
                .rounded_full()
                .object_fit(ObjectFit::Cover)
                .into_any_element(),
            None => ui::initial_avatar(if name.is_empty() { &self.queen_id } else { &name }, px(104.), &theme)
                .into_any_element(),
        };
        let removing = self.confirm == Some(Confirm::RemovePicture);
        let picture_tools = h_flex()
            .gap_1()
            .child(
                Button::new("picture")
                    .small()
                    .ghost()
                    .icon(IconName::Camera)
                    .tooltip("Change her picture (JPEG or PNG, up to 2 MB)")
                    .loading(self.busy == Some(Part::Picture))
                    .on_click(cx.listener(|this, _, window, cx| this.choose_picture(window, cx))),
            )
            .when(self.picture.is_some(), |row| {
                row.child(
                    Button::new("remove-picture")
                        .small()
                        .ghost()
                        .when(removing, |b| b.danger().label("Remove it"))
                        .when(!removing, |b| b.icon(IconName::Trash).tooltip("Remove her picture"))
                        .on_click(cx.listener(|this, _, window, cx| this.remove_picture(window, cx))),
                )
            });

        let identity = match &self.editor {
            Some(Editor::Identity { name: name_field, title: title_field }) => {
                let ready =
                    !name_field.read(cx).value().trim().is_empty() && !title_field.read(cx).value().trim().is_empty();
                v_flex()
                    .gap_2()
                    .w(px(380.))
                    .child(Input::new(name_field))
                    .child(Input::new(title_field).small())
                    .child(
                        h_flex()
                            .gap_2()
                            .child(
                                Button::new("identity-save")
                                    .small()
                                    .primary()
                                    .icon(IconName::Check)
                                    .label("Save")
                                    .loading(self.busy == Some(Part::Identity))
                                    .disabled(!ready)
                                    .on_click(cx.listener(|this, _, window, cx| this.save_identity(window, cx))),
                            )
                            .child(
                                Button::new("identity-cancel")
                                    .small()
                                    .ghost()
                                    .label("Cancel")
                                    .on_click(cx.listener(|this, _, _, cx| this.close_editor(cx))),
                            ),
                    )
                    .into_any_element()
            }
            _ => v_flex()
                .child(
                    h_flex().gap_2().child(div().text_2xl().font_semibold().child(name.clone())).child(
                        Button::new("identity-edit")
                            .small()
                            .ghost()
                            .icon(IconName::Pencil)
                            .tooltip("Edit her name and title")
                            .on_click(cx.listener(|this, _, window, cx| this.edit_identity(window, cx))),
                    ),
                )
                .when(!title.is_empty(), |col| col.child(div().text_color(theme.muted_foreground).child(title.clone())))
                .into_any_element(),
        };

        v_flex()
            .gap_5()
            .child(
                h_flex()
                    .gap_6()
                    .items_start()
                    // Wide enough for the confirm label, so arming Remove doesn't shift the page.
                    .child(
                        v_flex().w(px(150.)).flex_shrink_0().gap_2().items_center().child(picture).child(picture_tools),
                    )
                    .child(
                        v_flex()
                            .flex_1()
                            .min_w_0()
                            .gap_3()
                            .child(
                                h_flex()
                                    .justify_between()
                                    .child(
                                        div()
                                            .text_xs()
                                            .text_color(theme.muted_foreground)
                                            .child(format!("Queen · {}", self.queen_id)),
                                    )
                                    .child(
                                        Button::new("refresh")
                                            .small()
                                            .ghost()
                                            .icon(IconName::RefreshCw)
                                            .tooltip("Refresh")
                                            .on_click(cx.listener(|this, _, _, cx| this.load(cx))),
                                    ),
                            )
                            .child(identity)
                            .when_some(self.error_for(Part::Identity, &theme), |col, e| col.child(e))
                            .when_some(self.error_for(Part::Picture, &theme), |col, e| col.child(e))
                            .child(
                                h_flex().child(
                                    Button::new("message")
                                        .primary()
                                        .icon(IconName::MessageSquare)
                                        .label("Message")
                                        .on_click(cx.listener(|this, _, window, cx| {
                                            let route = Route::Queen(this.queen_id.clone());
                                            this.go(route, window, cx);
                                        })),
                                ),
                            ),
                    ),
            )
            .child(self.render_stats(cx))
            .into_any_element()
    }

    fn render_stats(&self, cx: &mut Context<Self>) -> Div {
        let mut stats: Vec<(&'static str, String)> = Vec::new();
        let memory = self
            .overview
            .as_ref()
            .map(|o| (o["memory"]["count"].as_i64().unwrap_or(0), o["memory"]["limit"].as_i64().unwrap_or(0)));
        if let Some(o) = &self.overview {
            stats.push(("Chats", o["sessions"]["count"].as_i64().unwrap_or(0).to_string()));
            let first = text(&o["sessions"], "first");
            if !first.is_empty() {
                stats.push(("With you since", first));
            }
            let last = text(&o["sessions"], "last_active");
            if !last.is_empty() {
                stats.push(("Last active", when(&last)));
            }
        }
        if let Some(Ok(soul)) = &self.soul
            && flag(soul, "enabled")
        {
            let version = soul["version"].as_i64().unwrap_or(0);
            let waiting = soul["proposal"]["edits"].as_array().map_or(0, Vec::len);
            let mut value = if version > 0 { format!("v{version}") } else { "—".into() };
            if waiting > 0 {
                value.push_str(&format!(" · {waiting} waiting"));
            }
            stats.push(("Soul", value));
        }
        if let Some(model) = self.current_model() {
            // Her model's own name reads better than its provider path.
            let model = text(&model, "model");
            stats.push(("Model", model.rsplit('/').next().unwrap_or(&model).to_string()));
        }

        let open_memory = cx.listener(|this, _, window, cx| this.go(Route::Page(Page::Memory), window, cx));
        let theme = cx.theme().clone();
        let cell = |label: &'static str, value: String| {
            v_flex()
                .px_4()
                .py_2()
                .rounded_lg()
                .border_1()
                .border_color(theme.border)
                .child(div().text_xs().text_color(theme.muted_foreground).child(label))
                .child(div().text_sm().font_medium().child(value))
        };
        h_flex()
            .gap_2()
            .flex_wrap()
            .when_some(memory, |row, (count, limit)| {
                row.child(
                    cell("Memories", format!("{count} of {limit}"))
                        .id("stat-memory")
                        .cursor_pointer()
                        .hover(|c| c.bg(theme.list_hover))
                        .on_click(open_memory),
                )
            })
            .children(stats.into_iter().map(|(label, value)| cell(label, value)))
    }

    /// Her own model's slot, else the main model's.
    fn current_model(&self) -> Option<Value> {
        let Some(Ok(models)) = &self.models else { return None };
        self.own_model(models).or_else(|| Some(models["slots"]["llm"].clone()).filter(|s| !s.is_null()))
    }

    fn own_model(&self, models: &Value) -> Option<Value> {
        models["queens"].as_array()?.iter().find(|q| text(q, "id") == self.queen_id).cloned()
    }

    fn render_persona(&self, persona: &Value, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        if let Some(Editor::Traits(field)) = &self.editor {
            return v_flex()
                .gap_2()
                .child(Textarea::new(field))
                .child(self.edit_foot(
                    "traits",
                    Part::Persona,
                    "Every chat with her starts from this text.",
                    Self::save_text,
                    cx,
                ))
                .when_some(self.error_for(Part::Persona, &theme), |col, e| col.child(e))
                .into_any_element();
        }
        let traits = text(persona, "core_traits");
        let edit = cx.listener(|this, _, window, cx| {
            let value = text(&this.persona_value(), "core_traits");
            let field = Self::textarea(value, 6, 30, window, cx);
            field.update(cx, |s, cx| s.set_cursor_position(end_of(&s.value()), window, cx));
            this.open_editor(Editor::Traits(field), cx);
        });
        ui::card(&theme)
            .items_start()
            .justify_between()
            .child(if traits.trim().is_empty() {
                ui::muted("Nothing written yet.", &theme)
            } else {
                div().flex_1().min_w_0().text_sm().child(traits)
            })
            .child(
                Button::new("traits-edit")
                    .small()
                    .ghost()
                    .icon(IconName::Pencil)
                    .tooltip("Edit her persona")
                    .on_click(edit),
            )
            .into_any_element()
    }

    fn render_pillars(&self, persona: &Value, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        let mut cards: Vec<AnyElement> = Vec::new();
        let mut missing: Vec<AnyElement> = Vec::new();
        let head = |title: &'static str, note: &'static str| {
            v_flex()
                .min_w_0()
                .child(div().text_sm().font_medium().child(title))
                .child(div().text_xs().text_color(theme.muted_foreground).child(note))
        };
        let frame =
            || v_flex().gap_3().px_4().py_3().rounded_lg().border_1().border_color(theme.border).bg(theme.background);

        for (ix, (key, title, note, _)) in PILLARS.into_iter().enumerate() {
            let fields = persona[key].as_object().filter(|m| !m.is_empty());
            match &self.editor {
                Some(Editor::Pillar { key: k, fields: editing }) if *k == key => {
                    let rows = editing.iter().map(|(k, field)| {
                        v_flex()
                            .gap_1()
                            .child(div().text_xs().text_color(theme.muted_foreground).child(label(k)))
                            .child(Textarea::new(field))
                    });
                    cards.push(
                        frame()
                            .child(head(title, note))
                            .children(rows)
                            .child(self.edit_foot(
                                "pillar",
                                Part::Pillars,
                                "Empty fields are left out.",
                                Self::save_pillar,
                                cx,
                            ))
                            .when_some(self.error_for(Part::Pillars, &theme), |col, e| col.child(e))
                            .into_any_element(),
                    );
                }
                _ => {
                    let edit = cx.listener(move |this, _, window, cx| this.edit_pillar(key, window, cx));
                    match fields {
                        Some(fields) => cards.push(
                            frame()
                                .child(
                                    h_flex().justify_between().child(head(title, note)).child(
                                        Button::new(("pillar-edit", ix))
                                            .small()
                                            .ghost()
                                            .icon(IconName::Pencil)
                                            .tooltip(format!("Edit {}", title.to_lowercase()))
                                            .on_click(edit),
                                    ),
                                )
                                .children(fields.iter().map(|(k, v)| {
                                    v_flex()
                                        .child(div().text_xs().text_color(theme.muted_foreground).child(label(k)))
                                        .child(div().text_sm().child(as_text(v)))
                                }))
                                .into_any_element(),
                        ),
                        None => missing.push(
                            Button::new(("pillar-add", ix))
                                .small()
                                .outline()
                                .icon(IconName::Plus)
                                .label(title)
                                .on_click(edit)
                                .into_any_element(),
                        ),
                    }
                }
            }
        }

        let (title, note) = ("Triggers", "What sets her off, and how she answers");
        let triggers = persona["behavior_triggers"].as_array().cloned().unwrap_or_default();
        match &self.editor {
            Some(Editor::Triggers(rows)) => {
                let rows = rows.iter().enumerate().map(|(ix, (when, then))| {
                    // Removed by its input, not its place: two quick clicks mustn't drop the wrong row.
                    let row_id = when.entity_id();
                    h_flex()
                        .gap_2()
                        .items_start()
                        .child(div().w(px(240.)).flex_shrink_0().child(Input::new(when).small()))
                        .child(div().flex_1().min_w_0().child(Textarea::new(then)))
                        .child(
                            Button::new(("trigger-drop", ix))
                                .small()
                                .ghost()
                                .icon(IconName::X)
                                .tooltip("Leave this one out")
                                .on_click(cx.listener(move |this, _, _, cx| {
                                    if let Some(Editor::Triggers(rows)) = &mut this.editor {
                                        rows.retain(|(when, _)| when.entity_id() != row_id);
                                    }
                                    cx.notify();
                                })),
                        )
                });
                cards.push(
                    frame()
                        .child(head(title, note))
                        .child(
                            h_flex()
                                .gap_2()
                                .text_xs()
                                .text_color(theme.muted_foreground)
                                .child(div().w(px(240.)).child("When"))
                                .child("She"),
                        )
                        .children(rows)
                        .child(
                            h_flex().child(
                                Button::new("trigger-add")
                                    .small()
                                    .ghost()
                                    .icon(IconName::Plus)
                                    .label("Add a trigger")
                                    .on_click(cx.listener(|this, _, window, cx| {
                                        let row = Self::trigger_row(String::new(), String::new(), window, cx);
                                        if let Some(Editor::Triggers(rows)) = &mut this.editor {
                                            rows.push(row);
                                        }
                                        cx.notify();
                                    })),
                            ),
                        )
                        .child(self.edit_foot(
                            "triggers",
                            Part::Pillars,
                            "A trigger needs both halves to be kept.",
                            Self::save_pillar,
                            cx,
                        ))
                        .when_some(self.error_for(Part::Pillars, &theme), |col, e| col.child(e))
                        .into_any_element(),
                );
            }
            _ => {
                let edit = cx.listener(|this, _, window, cx| this.edit_triggers(window, cx));
                if triggers.is_empty() {
                    missing.push(
                        Button::new("triggers-add")
                            .small()
                            .outline()
                            .icon(IconName::Plus)
                            .label(title)
                            .on_click(edit)
                            .into_any_element(),
                    );
                } else {
                    cards.push(
                        frame()
                            .child(
                                h_flex().justify_between().child(head(title, note)).child(
                                    Button::new("triggers-edit")
                                        .small()
                                        .ghost()
                                        .icon(IconName::Pencil)
                                        .tooltip("Edit triggers")
                                        .on_click(edit),
                                ),
                            )
                            .children(triggers.iter().map(|t| {
                                h_flex()
                                    .gap_2()
                                    .items_start()
                                    .text_sm()
                                    .child(div().w(px(240.)).flex_shrink_0().child(text(t, "trigger")))
                                    .child(div().text_color(theme.muted_foreground).child("→"))
                                    .child(div().flex_1().min_w_0().child(text(t, "reaction")))
                            }))
                            .into_any_element(),
                    );
                }
            }
        }

        v_flex()
            .gap_3()
            .children(cards)
            .when(!missing.is_empty(), |col| col.child(h_flex().gap_2().flex_wrap().children(missing)))
            // An error while no editor is open, e.g. from a save that closed it.
            .when(!matches!(self.editor, Some(Editor::Pillar { .. } | Editor::Triggers(_))), |col| {
                col.when_some(self.error_for(Part::Pillars, &theme), |col, e| col.child(e))
            })
            .into_any_element()
    }

    fn render_craft(&self, persona: &Value, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        if let Some(Editor::Skills(field)) = &self.editor {
            return v_flex()
                .gap_2()
                .child(Textarea::new(field))
                .child(self.edit_foot("skills", Part::Craft, "Separate skills with commas.", Self::save_text, cx))
                .when_some(self.error_for(Part::Craft, &theme), |col, e| col.child(e))
                .into_any_element();
        }
        let skills = split_skills(&text(persona, "skills"));
        let edit = cx.listener(|this, _, window, cx| {
            let value = text(&this.persona_value(), "skills");
            let field = Self::textarea(value, 3, 12, window, cx);
            field.update(cx, |s, cx| s.set_cursor_position(end_of(&s.value()), window, cx));
            this.open_editor(Editor::Skills(field), cx);
        });
        let has_skills = !skills.is_empty();
        h_flex()
            .gap_2()
            .flex_wrap()
            .children(skills.into_iter().map(|skill| {
                div()
                    .px_3()
                    .py_1()
                    .rounded_full()
                    .border_1()
                    .border_color(theme.border)
                    .bg(theme.muted)
                    .text_sm()
                    .child(skill)
            }))
            .child(
                Button::new("skills-edit")
                    .small()
                    .ghost()
                    .icon(if has_skills { IconName::Pencil } else { IconName::Plus })
                    .label(if has_skills { "Edit" } else { "Say what she is good at" })
                    .on_click(edit),
            )
            .into_any_element()
    }

    fn render_picker(&self, search: &Entity<InputState>, models: &Value, cx: &mut Context<Self>) -> AnyElement {
        let query = search.read(cx).value().to_lowercase();
        let matches = |s: &str| query.is_empty() || s.to_lowercase().contains(&query);
        let mut groups: Vec<(String, Vec<PickerRow>)> = Vec::new();
        for endpoint in self.endpoints().iter().filter(|e| flag(e, "running")) {
            let name = text(endpoint, "name");
            let rows = match self.endpoint_models.get(&name) {
                Some(Ok(list)) => list
                    .iter()
                    .filter(|m| matches(&text(m, "id")))
                    .map(|m| {
                        (
                            text(m, "id"),
                            context_label(m["max_context_tokens"].as_i64()).unwrap_or_default(),
                            Some(Choice::Endpoint { endpoint: name.clone(), model: text(m, "id") }),
                        )
                    })
                    .collect(),
                Some(Err(e)) => vec![(format!("Can't list models: {e}"), String::new(), None)],
                None => vec![("Loading…".into(), String::new(), None)],
            };
            // A search that leaves an endpoint nothing drops its heading too.
            if !rows.is_empty() {
                groups.push((if flag(endpoint, "builtin") { "Magpie".into() } else { name.clone() }, rows));
            }
        }
        for provider in models["providers"].as_array().into_iter().flatten().filter(|p| flag(p, "connected")) {
            let id = text(provider, "id");
            let rows: Vec<_> = provider["models"]
                .as_array()
                .into_iter()
                .flatten()
                .filter(|m| matches(&text(m, "id")) || matches(&text(m, "label")))
                .map(|m| {
                    let label = Some(text(m, "label")).filter(|l| !l.is_empty()).unwrap_or_else(|| text(m, "id"));
                    (
                        label,
                        context_label(m["max_context_tokens"].as_i64()).unwrap_or_default(),
                        Some(Choice::Catalog { provider: id.clone(), model: text(m, "id") }),
                    )
                })
                .collect();
            if !rows.is_empty() {
                groups.push((id.clone(), rows));
            }
        }

        let theme = cx.theme().clone();
        let mut row_ix = 0usize;
        let mut list = v_flex().gap_1();
        if groups.is_empty() {
            list = list.child(
                ui::muted("No models match. Connect a provider or start an endpoint on the Models page.", &theme)
                    .px_2(),
            );
        }
        for (title, rows) in groups {
            list = list
                .child(div().px_2().pt_2().text_xs().font_semibold().text_color(theme.muted_foreground).child(title));
            for (label, note, choice) in rows {
                row_ix += 1;
                list = list.child(
                    h_flex()
                        .id(("model-choice", row_ix))
                        .justify_between()
                        .px_2()
                        .py_1()
                        .rounded_md()
                        .text_sm()
                        .when(choice.is_some(), |row| row.cursor_pointer().hover(|row| row.bg(theme.list_hover)))
                        .when(choice.is_none(), |row| row.text_color(theme.muted_foreground))
                        .child(div().truncate().child(label))
                        .child(div().text_xs().text_color(theme.muted_foreground).child(note))
                        .when_some(choice, |row, choice| {
                            row.on_click(cx.listener(move |this, _, _, cx| this.pick(Some(choice.clone()), cx)))
                        }),
                );
            }
        }
        v_flex()
            .gap_2()
            .p_3()
            .rounded_lg()
            .border_1()
            .border_color(theme.border)
            .bg(theme.sidebar)
            .child(Input::new(search).small())
            .child(div().id("model-list").max_h(px(320.)).overflow_y_scroll().child(list))
            .into_any_element()
    }

    fn render_model(&self, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        let models = match &self.models {
            None => return Spinner::new().small().into_any_element(),
            Some(Err(e)) => return ui::error_line(format!("Couldn't load the models: {e}"), &theme).into_any_element(),
            Some(Ok(models)) => models.clone(),
        };
        let own = self.own_model(&models);
        let main = &models["slots"]["llm"];
        let (line, note) = match &own {
            Some(own) => (model_summary(own), "Her own model. Her running chats use it now."),
            None => (
                format!("Main model · {}", if main.is_null() { "not set".to_string() } else { model_summary(main) }),
                "She uses the main model from the Models page.",
            ),
        };
        let card = ui::card(&theme)
            .justify_between()
            .child(
                h_flex()
                    .gap_3()
                    .min_w_0()
                    .child(Icon::new(IconName::Cpu).small().text_color(theme.muted_foreground))
                    .child(
                        v_flex()
                            .min_w_0()
                            .child(div().text_sm().font_medium().truncate().child(line))
                            .child(div().text_xs().text_color(theme.muted_foreground).child(note)),
                    ),
            )
            .child(
                h_flex()
                    .gap_2()
                    .when(self.busy == Some(Part::Model), |row| row.child(Spinner::new().small()))
                    .when(own.is_some(), |row| {
                        row.child(
                            Button::new("model-reset")
                                .small()
                                .ghost()
                                .label("Use the main model")
                                .on_click(cx.listener(|this, _, _, cx| this.pick(None, cx))),
                        )
                    })
                    .child(
                        Button::new("model-change")
                            .small()
                            .outline()
                            .label("Change")
                            .selected(self.picker.is_some())
                            .on_click(cx.listener(|this, _, window, cx| this.open_picker(window, cx))),
                    ),
            );
        v_flex()
            .gap_2()
            .child(card)
            .when_some(self.picker.clone(), |col, search| col.child(self.render_picker(&search, &models, cx)))
            .when_some(self.error_for(Part::Model, &theme), |col, e| col.child(e))
            .into_any_element()
    }

    fn render_memory(&self, cx: &mut Context<Self>) -> AnyElement {
        let open = cx.listener(|this, _, window, cx| this.go(Route::Page(Page::Memory), window, cx));
        let theme = cx.theme().clone();
        let Some(overview) = &self.overview else {
            return ui::muted("Her numbers couldn't be read.", &theme).into_any_element();
        };
        let memory = &overview["memory"];
        let mut kinds: Vec<(String, i64)> = memory["by_type"]
            .as_object()
            .into_iter()
            .flatten()
            .map(|(k, v)| (label(k), v.as_i64().unwrap_or(0)))
            .collect();
        kinds.sort_by_key(|k| std::cmp::Reverse(k.1));
        ui::card(&theme)
            .justify_between()
            .child(
                v_flex()
                    .gap_1()
                    .child(
                        h_flex()
                            .gap_2()
                            .items_end()
                            .child(div().text_xl().font_semibold().child(text(memory, "count")))
                            .child(
                                div()
                                    .text_sm()
                                    .text_color(theme.muted_foreground)
                                    .child(format!("of {} notes", text(memory, "limit"))),
                            ),
                    )
                    .when(!kinds.is_empty(), |col| {
                        col.child(
                            div()
                                .text_xs()
                                .text_color(theme.muted_foreground)
                                .child(kinds.iter().map(|(k, n)| format!("{k} {n}")).collect::<Vec<_>>().join(" · ")),
                        )
                    }),
            )
            .child(
                Button::new("open-memory")
                    .small()
                    .outline()
                    .icon(IconName::Library)
                    .label("Open memories")
                    .on_click(open),
            )
            .into_any_element()
    }

    fn render_soul(&self, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        let soul = match &self.soul {
            None => return Spinner::new().small().into_any_element(),
            Some(Err(e)) => return ui::error_line(format!("Couldn't load her soul: {e}"), &theme).into_any_element(),
            Some(Ok(soul)) => soul.clone(),
        };
        if !flag(&soul, "enabled") {
            return ui::muted(format!("She has no soul yet. To give her one, add her to configuration.json under soul.queens, e.g. \"soul\": {{\"queens\": {{\"{}\": {{}}}}}}.", self.queen_id), &theme).into_any_element();
        }
        let version = soul["version"].as_i64().unwrap_or(0);
        let reflecting = flag(&soul, "reflecting");
        let proposal = soul["proposal"].clone();
        let history = soul["history"].as_array().cloned().unwrap_or_default();
        let sections = soul["sections"].as_array().cloned().unwrap_or_default();
        let busy = self.busy == Some(Part::Soul);

        let mut line = format!(
            "{} · reflects daily after {}:00",
            if text(&soul, "mode") == "review" {
                "Her changes wait for your approval"
            } else {
                "Her changes apply at once"
            },
            text(&soul, "hour")
        );
        let last_run = text(&soul, "last_run");
        if !last_run.is_empty() {
            line.push_str(&format!(" · last {last_run}: {}", text(&soul, "last_result")));
        }
        let status = ui::card(&theme)
            .justify_between()
            .child(
                v_flex()
                    .min_w_0()
                    .child(div().text_sm().font_medium().child(if version > 0 {
                        format!("Version {version}")
                    } else {
                        "Not written yet".into()
                    }))
                    .child(div().text_xs().text_color(theme.muted_foreground).child(line)),
            )
            .child(
                h_flex()
                    .gap_2()
                    .when(reflecting, |row| {
                        row.child(Spinner::new().small())
                            .child(div().text_xs().text_color(theme.muted_foreground).child("Reflecting…"))
                    })
                    .child(
                        Button::new("soul-reflect")
                            .small()
                            .outline()
                            .icon(IconName::Sparkles)
                            .label(if version == 0 { "Write the first draft" } else { "Reflect now" })
                            .loading(busy)
                            .disabled(reflecting || !proposal.is_null())
                            .when(!proposal.is_null(), |b| b.tooltip("Decide on the waiting changes first"))
                            .on_click(cx.listener(move |this, _, _, cx| {
                                this.soul_action("reflect".into(), json!({ "bootstrap": version == 0 }), cx)
                            })),
                    )
                    .when(!history.is_empty(), |row| {
                        row.child(
                            Button::new("soul-history")
                                .small()
                                .ghost()
                                .label("History")
                                .selected(self.show_history)
                                .on_click(cx.listener(|this, _, _, cx| {
                                    this.show_history = !this.show_history;
                                    cx.notify();
                                })),
                        )
                    }),
            );

        let titles: HashMap<String, String> = sections.iter().map(|s| (text(s, "key"), text(s, "title"))).collect();
        let proposal_block = (!proposal.is_null()).then(|| {
            let edits = proposal["edits"].as_array().cloned().unwrap_or_default();
            let count = edits.len();
            let id = text(&proposal, "id");
            let dismissing = self.confirm == Some(Confirm::Dismiss);
            let decide_id = id.clone();
            v_flex()
                .gap_2()
                .px_4()
                .py_3()
                .rounded_lg()
                .border_1()
                .border_color(theme.primary)
                .child(div().text_xs().font_semibold().text_color(theme.primary).child("WAITING FOR YOU"))
                .child(div().text_sm().font_semibold().child(format!(
                    "{} · {count} {}",
                    if flag(&proposal, "bootstrap") { "Her first draft" } else { "Her reflection" },
                    if count == 1 { "change" } else { "changes" }
                )))
                .when(!text(&proposal, "summary").is_empty(), |col| {
                    col.child(ui::muted(text(&proposal, "summary"), &theme))
                })
                .children(edits.iter().map(|edit| {
                    let op = text(edit, "op");
                    let mark = match op.as_str() {
                        "add" => "+",
                        "remove" => "−",
                        _ => "~",
                    };
                    let section = titles.get(&text(edit, "section")).cloned().unwrap_or_else(|| text(edit, "section"));
                    h_flex().gap_3().items_start().child(div().w(px(14.)).text_sm().font_semibold().child(mark)).child(
                        v_flex()
                            .min_w_0()
                            .child(div().text_xs().text_color(theme.muted_foreground).child(if flag(edit, "expired") {
                                format!("{section} · too old")
                            } else {
                                section
                            }))
                            .when(op != "add", |col| {
                                col.child(
                                    div()
                                        .text_sm()
                                        .text_color(theme.muted_foreground)
                                        .line_through()
                                        .child(text(edit, "old")),
                                )
                            })
                            .when(op != "remove", |col| col.child(div().text_sm().child(text(edit, "text")))),
                    )
                }))
                .child(
                    h_flex()
                        .gap_2()
                        .child(
                            Button::new("soul-apply")
                                .small()
                                .primary()
                                .label(format!("Apply all ({count})"))
                                .loading(busy)
                                .on_click(cx.listener(move |this, _, _, cx| {
                                    this.confirm = None;
                                    let accept: Vec<usize> = (0..count).collect();
                                    this.soul_action(
                                        format!("proposals/{decide_id}/decide"),
                                        json!({ "accept": accept }),
                                        cx,
                                    );
                                })),
                        )
                        .child(
                            Button::new("soul-dismiss")
                                .small()
                                .ghost()
                                .when(dismissing, |b| b.danger().label(format!("Dismiss all {count} for good")))
                                .when(!dismissing, |b| b.label("Dismiss"))
                                .on_click(cx.listener(move |this, _, _, cx| {
                                    if this.confirmed(Confirm::Dismiss, cx) {
                                        this.soul_action(format!("proposals/{id}/decide"), json!({ "accept": [] }), cx);
                                    }
                                })),
                        ),
                )
        });

        let section_cards = sections.iter().map(|s| {
            let items = s["items"].as_array().cloned().unwrap_or_default();
            let over = s["used"].as_i64().unwrap_or(0) > s["limit"].as_i64().unwrap_or(i64::MAX);
            v_flex()
                .gap_2()
                .px_4()
                .py_3()
                .rounded_lg()
                .border_1()
                .border_color(theme.border)
                .child(
                    h_flex().justify_between().child(div().text_sm().font_medium().child(text(s, "title"))).child(
                        div()
                            .text_xs()
                            .text_color(if over { theme.danger } else { theme.muted_foreground })
                            .child(format!("{} / {}", text(s, "used"), text(s, "limit"))),
                    ),
                )
                .when(items.is_empty(), |col| col.child(ui::muted("Nothing here yet.", &theme)))
                .children(items.iter().map(|item| {
                    h_flex()
                        .gap_3()
                        .justify_between()
                        .items_start()
                        .text_sm()
                        .child(div().flex_1().min_w_0().child(text(item, "text")))
                        .child(div().text_xs().text_color(theme.muted_foreground).child(text(item, "date")))
                }))
        });

        let history_list = (self.show_history && !history.is_empty()).then(|| {
            v_flex().gap_1().px_4().py_3().rounded_lg().border_1().border_color(theme.border).children(
                history.iter().enumerate().map(|(ix, v)| {
                    let number = v["version"].as_i64().unwrap_or(0);
                    let confirming = self.confirm == Some(Confirm::Restore(number));
                    h_flex()
                        .gap_3()
                        .text_sm()
                        .child(div().w(px(40.)).font_semibold().child(format!("v{number}")))
                        .child(
                            div().w(px(130.)).text_xs().text_color(theme.muted_foreground).child(when(&text(v, "at"))),
                        )
                        .child(div().flex_1().min_w_0().truncate().text_color(theme.muted_foreground).child(format!(
                            "{} · {}",
                            text(v, "author"),
                            text(v, "note")
                        )))
                        .child(if number == version {
                            div().text_xs().text_color(theme.success).child("Current").into_any_element()
                        } else {
                            Button::new(("soul-restore", ix))
                                .small()
                                .ghost()
                                .when(confirming, |b| b.danger().label(format!("Make v{number} current")))
                                .when(!confirming, |b| b.icon(IconName::RotateCcw).label("Restore"))
                                .on_click(cx.listener(move |this, _, _, cx| {
                                    if this.confirmed(Confirm::Restore(number), cx) {
                                        this.soul_action("rollback".into(), json!({ "version": number }), cx);
                                    }
                                }))
                                .into_any_element()
                        })
                }),
            )
        });

        v_flex()
            .gap_3()
            .child(status)
            .when_some(proposal_block, |col, block| col.child(block))
            .children(section_cards)
            .when_some(history_list, |col, list| col.child(list))
            .when_some(self.error_for(Part::Soul, &theme), |col, e| col.child(e))
            .into_any_element()
    }
}

impl Render for ProfilePage {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let theme = cx.theme().clone();
        let body = div().id("profile-body").size_full().overflow_y_scroll();
        let persona =
            match self.persona.clone() {
                None => return body.child(v_flex().p_8().child(Spinner::new())),
                Some(Err(e)) => {
                    return body.child(v_flex().p_8().gap_3().items_start().child(ui::error_line(e, &theme)).child(
                        Button::new("all-queens").small().outline().label("See all queens").on_click(
                            cx.listener(|this, _, window, cx| this.go(Route::Page(Page::OrgChart), window, cx)),
                        ),
                    ));
                }
                Some(Ok(persona)) => persona,
            };
        let lede = |text: &'static str| ui::muted(text, &theme);
        body.child(
            v_flex()
                .gap_8()
                .px_8()
                .py_6()
                .w_full()
                .max_w(px(880.))
                .mx_auto()
                .child(self.render_hero(&persona, cx))
                .child(
                    ui::section("Persona", &theme)
                        .child(lede("The text every chat with her starts from."))
                        .child(self.render_persona(&persona, cx)),
                )
                .child(
                    ui::section("Beneath the surface", &theme)
                        .child(lede("The pillars her identity is built from besides that text."))
                        .child(self.render_pillars(&persona, cx)),
                )
                .child(
                    ui::section("Soul", &theme)
                        .child(lede("Her own notes about herself, revised once a day from her chats."))
                        .child(self.render_soul(cx)),
                )
                .child(
                    ui::section("Model", &theme)
                        .child(lede("The model behind her voice."))
                        .child(self.render_model(cx)),
                )
                .child(
                    ui::section("Memory", &theme)
                        .child(lede("The notes she keeps across chats."))
                        .child(self.render_memory(cx)),
                )
                .child(
                    ui::section("Craft", &theme)
                        .child(lede("What she is good at, in her own profile's words."))
                        .child(self.render_craft(&persona, cx)),
                ),
        )
    }
}

#[cfg(test)]
mod tests {
    // Not `super::*`: that brings GPUI's own `test` attribute along.
    use super::{label, picture_kind, split_skills};

    #[test]
    fn skills_split_outside_brackets() {
        assert_eq!(split_skills("drawing (ink, watercolor), teasing"), vec!["drawing (ink, watercolor)", "teasing"]);
        assert_eq!(split_skills("  a ;b\n\nc, "), vec!["a", "b", "c"]);
        assert!(split_skills(" , ").is_empty());
    }

    #[test]
    fn labels_read_as_words() {
        assert_eq!(label("past_wound"), "Past wound");
        assert_eq!(label(""), "");
    }

    #[test]
    fn only_jpeg_and_png_pass() {
        assert!(picture_kind(&[0x89, b'P', b'N', b'G', 0x0D]).is_some());
        assert!(picture_kind(&[0xFF, 0xD8, 0xFF]).is_some());
        assert!(picture_kind(b"RIFF\0\0\0\0WEBPVP8 ").is_none());
        assert!(picture_kind(b"GIF89a").is_none());
    }
}
