//! Which model each role uses, and the endpoints, keys, saved setups and subscriptions behind them.
//! Mirrors `frontend/src/pages/models.tsx`.

use std::collections::{BTreeMap, HashMap};

use gpui_kit::assets::IconName;
use gpui_kit::base::{h_flex, v_flex};
use gpui_kit::component::button::{Button, ButtonVariants as _};
use gpui_kit::component::input::{Input, InputState};
use gpui_kit::component::spinner::Spinner;
use gpui_kit::component::{ActiveTheme as _, Icon, Sizable as _, StyledExt as _};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;
use serde_json::{Value, json};

use super::{flag, text};
use crate::api::api;
use crate::{bg, ui};

/// The role slots in the order the page shows them: (slot, label, what an empty slot means).
const ROLES: [(&str, &str, &str); 3] = [
    ("llm", "Main model", "Not set"),
    ("worker_llm", "Workers", "Same as the main model"),
    ("vision_fallback", "Vision fallback", "None"),
];

/// One thing a slot can be set to.
#[derive(Clone)]
enum Choice {
    Saved(String),
    Endpoint { endpoint: String, model: String },
    Catalog { provider: String, model: String },
}

/// A picker row: label, a note such as the context size, and what picking it does.
type PickerRow = (String, String, Choice);

struct Picker {
    slot: &'static str,
    search: Entity<InputState>,
}

pub struct ModelsPage {
    overview: Option<Result<Value, String>>,
    library: BTreeMap<String, Value>,
    /// A running endpoint's models, fetched when a picker first needs them.
    endpoint_models: HashMap<String, Result<Vec<Value>, String>>,
    picker: Option<Picker>,
    /// The slot being written, while it is.
    saving: Option<String>,
    error: Option<String>,
    new_endpoint: [Entity<InputState>; 3],
    /// Provider whose key is being typed, and the field it's typed in.
    key_entry: Option<(String, Entity<InputState>)>,
    /// A saved setup the user asked to delete; a second click confirms.
    confirm_delete: Option<String>,
    tasks: Vec<Task<()>>,
}

fn context_label(tokens: Option<i64>) -> Option<String> {
    match tokens? {
        t if t >= 1_000_000 => Some(format!("{}M", (t as f64 / 100_000.0).round() / 10.0)),
        t if t > 0 => Some(format!("{}k", (t as f64 / 1000.0).round() as i64)),
        _ => None,
    }
}

/// "model · where it comes from · context", as the page summarises a slot.
fn summary(slot: &Value) -> String {
    let source = match text(slot, "source").as_str() {
        "endpoint" => text(slot, "endpoint"),
        "subscription" => text(slot, "subscription"),
        _ => text(slot, "provider"),
    };
    let mut parts = vec![text(slot, "model")];
    if !source.is_empty() {
        parts.push(source);
    }
    if let Some(context) = context_label(slot["max_context_tokens"].as_i64()) {
        parts.push(format!("{context} context"));
    }
    parts.join(" · ")
}

fn is_judge(setup: &Value) -> bool {
    !text(setup, "protocol").is_empty()
}

fn key_note(setup: &Value) -> Option<String> {
    if !text(setup, "api_key").is_empty() {
        Some("key saved".into())
    } else {
        let var = text(setup, "api_key_env_var");
        (!var.is_empty()).then(|| format!("key from ${var}"))
    }
}

impl ModelsPage {
    pub fn new(window: &mut Window, cx: &mut Context<Self>) -> Self {
        let field = |placeholder: &'static str, masked: bool, window: &mut Window, cx: &mut Context<Self>| {
            cx.new(|cx| InputState::new(window, cx).placeholder(placeholder).masked(masked))
        };
        let new_endpoint = [
            field("ollama", false, window, cx),
            field("http://localhost:11434/v1", false, window, cx),
            field("API key (optional)", true, window, cx),
        ];
        let mut page = Self {
            overview: None,
            library: BTreeMap::new(),
            endpoint_models: HashMap::new(),
            picker: None,
            saving: None,
            error: None,
            new_endpoint,
            key_entry: None,
            confirm_delete: None,
            tasks: Vec::new(),
        };
        page.load(cx);
        page
    }

    fn load(&mut self, cx: &mut Context<Self>) {
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || {
                let overview = api.get("/models/overview")?;
                let library = api.get("/config/provider-library")?;
                anyhow::Ok((overview, library))
            },
            |this: &mut Self, loaded, _| match loaded {
                Ok((overview, library)) => {
                    this.library =
                        library["library"].as_object().map(|m| m.clone().into_iter().collect()).unwrap_or_default();
                    this.overview = Some(Ok(overview));
                }
                Err(e) => this.overview = Some(Err(e.to_string())),
            },
        ));
    }

    /// Run a write, then reload the page; failures show at the top.
    fn write(
        &mut self,
        label: String,
        work: impl FnOnce(crate::api::Api) -> anyhow::Result<Value> + Send + 'static,
        cx: &mut Context<Self>,
    ) {
        self.saving = Some(label);
        self.error = None;
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || work(api),
            |this: &mut Self, done, cx| {
                this.saving = None;
                match done {
                    Ok(_) => {
                        this.picker = None;
                        this.load(cx);
                    }
                    Err(e) => this.error = Some(e.to_string()),
                }
            },
        ));
        cx.notify();
    }

    fn pick(&mut self, slot: &'static str, choice: Choice, cx: &mut Context<Self>) {
        self.write(
            slot.to_string(),
            move |api| match choice {
                Choice::Saved(name) => {
                    api.post("/config/provider-library/apply", json!({ "name": name, "role": slot }))
                }
                Choice::Endpoint { endpoint, model } => api.put(
                    &format!("/models/slots/{slot}"),
                    json!({ "source": "endpoint", "endpoint": endpoint, "model": model }),
                ),
                Choice::Catalog { provider, model } => api.put(
                    &format!("/models/slots/{slot}"),
                    json!({ "source": "catalog", "provider": provider, "model": model }),
                ),
            },
            cx,
        );
    }

    fn open_picker(&mut self, slot: &'static str, window: &mut Window, cx: &mut Context<Self>) {
        if self.picker.as_ref().is_some_and(|p| p.slot == slot) {
            self.picker = None;
            cx.notify();
            return;
        }
        let search = cx.new(|cx| InputState::new(window, cx).placeholder("Search models"));
        cx.observe(&search, |_, _, cx| cx.notify()).detach();
        search.update(cx, |state, cx| state.focus(window, cx));
        self.picker = Some(Picker { slot, search });
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
        match &self.overview {
            Some(Ok(o)) => o["endpoints"].as_array().cloned().unwrap_or_default(),
            _ => Vec::new(),
        }
    }

    fn add_endpoint(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let [name, base, key] = self.new_endpoint.clone();
        let name_v = name.read(cx).value().trim().to_string();
        let base_v = base.read(cx).value().trim().to_string();
        let key_v = key.read(cx).value().trim().to_string();
        if name_v.is_empty() || base_v.is_empty() {
            self.error = Some("An endpoint needs a name and an address.".into());
            cx.notify();
            return;
        }
        for field in [name, base, key] {
            field.update(cx, |s, cx| s.set_value("", window, cx));
        }
        let mut body = json!({ "api_base": base_v });
        if !key_v.is_empty() {
            body["api_key"] = json!(key_v);
        }
        self.write(format!("endpoint {name_v}"), move |api| api.put(&format!("/models/endpoints/{name_v}"), body), cx);
    }

    fn render_picker(&self, picker: &Picker, cx: &mut Context<Self>) -> AnyElement {
        let query = picker.search.read(cx).value().to_lowercase();
        let matches = |s: &str| query.is_empty() || s.to_lowercase().contains(&query);
        let slot = picker.slot;
        let mut groups: Vec<(String, Vec<PickerRow>)> = Vec::new();

        let saved: Vec<_> = self
            .library
            .iter()
            .filter(|(name, setup)| !is_judge(setup) && (matches(name) || matches(&text(setup, "model"))))
            .map(|(name, setup)| (name.clone(), text(setup, "model"), Choice::Saved(name.clone())))
            .collect();
        if !saved.is_empty() {
            groups.push(("Saved setups".into(), saved));
        }
        for endpoint in self.endpoints().iter().filter(|e| flag(e, "running")) {
            let name = text(endpoint, "name");
            let rows = match self.endpoint_models.get(&name) {
                Some(Ok(models)) => models
                    .iter()
                    .filter(|m| matches(&text(m, "id")))
                    .map(|m| {
                        (
                            text(m, "id"),
                            context_label(m["max_context_tokens"].as_i64()).unwrap_or_default(),
                            Choice::Endpoint { endpoint: name.clone(), model: text(m, "id") },
                        )
                    })
                    .collect(),
                Some(Err(e)) => vec![(format!("Can't list models: {e}"), String::new(), Choice::Saved(String::new()))],
                None => vec![("Loading…".into(), String::new(), Choice::Saved(String::new()))],
            };
            // A search that leaves an endpoint nothing drops its heading too.
            if !rows.is_empty() {
                groups.push((if flag(endpoint, "builtin") { "Magpie".into() } else { name.clone() }, rows));
            }
        }
        if let Some(Ok(overview)) = &self.overview {
            for provider in overview["providers"].as_array().into_iter().flatten().filter(|p| flag(p, "connected")) {
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
                            Choice::Catalog { provider: id.clone(), model: text(m, "id") },
                        )
                    })
                    .collect();
                if !rows.is_empty() {
                    groups.push((id.clone(), rows));
                }
            }
        }

        let theme = cx.theme().clone();
        let mut row_ix = 0usize;
        let mut list = v_flex().gap_1();
        for (title, rows) in groups {
            list = list
                .child(div().px_2().pt_2().text_xs().font_semibold().text_color(theme.muted_foreground).child(title));
            for (label, note, choice) in rows {
                row_ix += 1;
                let selectable = !matches!(&choice, Choice::Saved(n) if n.is_empty());
                list = list.child(
                    h_flex()
                        .id(("choice", row_ix))
                        .justify_between()
                        .px_2()
                        .py_1()
                        .rounded_md()
                        .text_sm()
                        .when(selectable, |row| row.cursor_pointer().hover(|row| row.bg(theme.list_hover)))
                        .when(!selectable, |row| row.text_color(theme.muted_foreground))
                        .child(div().truncate().child(label))
                        .child(div().text_xs().text_color(theme.muted_foreground).child(note))
                        .when(selectable, |row| {
                            row.on_click(cx.listener(move |this, _, _, cx| this.pick(slot, choice.clone(), cx)))
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
            .child(Input::new(&picker.search).small())
            .child(div().id("picker-list").max_h(px(360.)).overflow_y_scroll().child(list))
            .into_any_element()
    }

    fn render_roles(&self, overview: &Value, cx: &mut Context<Self>) -> AnyElement {
        let mut rows = Vec::new();
        for (slot, label, empty) in ROLES {
            let current = &overview["slots"][slot];
            let saving = self.saving.as_deref() == Some(slot);
            let theme = cx.theme();
            let mut card = v_flex().gap_2().child(
                ui::card(theme)
                    .justify_between()
                    .child(v_flex().min_w_0().child(div().text_sm().font_medium().child(label)).child(
                        div().text_sm().text_color(theme.muted_foreground).truncate().child(if current.is_null() {
                            empty.to_string()
                        } else {
                            summary(current)
                        }),
                    ))
                    .child(
                        h_flex()
                            .gap_2()
                            .when(saving, |row| row.child(Spinner::new().small()))
                            .when(slot != "llm" && !current.is_null(), |row| {
                                row.child(Button::new(("reset", slot.len())).small().ghost().label("Reset").on_click(
                                    cx.listener(move |this, _, _, cx| {
                                        this.write(
                                            slot.to_string(),
                                            move |api| api.delete(&format!("/models/slots/{slot}")),
                                            cx,
                                        )
                                    }),
                                ))
                            })
                            .child(
                                Button::new(SharedString::from(format!("change-{slot}")))
                                    .small()
                                    .outline()
                                    .label("Change")
                                    .on_click(
                                        cx.listener(move |this, _, window, cx| this.open_picker(slot, window, cx)),
                                    ),
                            ),
                    ),
            );
            if let Some(picker) = self.picker.as_ref().filter(|p| p.slot == slot) {
                card = card.child(self.render_picker(picker, cx));
            }
            rows.push(card.into_any_element());
        }

        // The judge's setup is written whole, so it comes from saved setups that carry a protocol.
        let judges: Vec<String> = self.library.iter().filter(|(_, s)| is_judge(s)).map(|(n, _)| n.clone()).collect();
        let judge = &overview["judge"];
        let theme = cx.theme();
        let judge_text = if flag(judge, "configured") {
            format!("{} · {}", text(judge, "model"), text(judge, "api_base"))
        } else {
            "Not set".into()
        };
        rows.push(
            ui::card(theme)
                .justify_between()
                .child(
                    v_flex()
                        .min_w_0()
                        .child(div().text_sm().font_medium().child("Judge"))
                        .child(div().text_sm().text_color(theme.muted_foreground).truncate().child(judge_text)),
                )
                .child(h_flex().gap_1().children(judges.into_iter().enumerate().map(|(ix, name)| {
                    let label = format!("Use {name}");
                    Button::new(("judge", ix)).small().outline().label(label).on_click(
                        cx.listener(move |this, _, _, cx| this.pick("judge", Choice::Saved(name.clone()), cx)),
                    )
                })))
                .into_any_element(),
        );
        v_flex().gap_2().children(rows).into_any_element()
    }

    fn render_endpoints(&self, overview: &Value, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        let rows =
            overview["endpoints"].as_array().cloned().unwrap_or_default().into_iter().enumerate().map(|(ix, e)| {
                let name = text(&e, "name");
                let builtin = flag(&e, "builtin");
                let running = flag(&e, "running");
                ui::card(&theme)
                    .justify_between()
                    .child(
                        h_flex()
                            .gap_3()
                            .child(ui::dot(if running { theme.success } else { theme.muted_foreground }))
                            .child(
                                v_flex()
                                    .child(div().text_sm().font_medium().child(if builtin {
                                        "Magpie".to_string()
                                    } else {
                                        name.clone()
                                    }))
                                    .child(div().text_xs().text_color(theme.muted_foreground).child(format!(
                                        "{} · {}{}",
                                        text(&e, "api_base"),
                                        if running { "Running" } else { "Not running" },
                                        if flag(&e, "has_key") { " · key saved" } else { "" }
                                    ))),
                            ),
                    )
                    .when(!builtin, |row| {
                        row.child(
                            Button::new(("del-endpoint", ix))
                                .small()
                                .ghost()
                                .icon(IconName::Trash)
                                .tooltip("Remove")
                                .on_click(cx.listener(move |this, _, _, cx| {
                                    let name = name.clone();
                                    this.write(
                                        format!("endpoint {name}"),
                                        move |api| api.delete(&format!("/models/endpoints/{name}")),
                                        cx,
                                    )
                                })),
                        )
                    })
            });
        let [name, base, key] = &self.new_endpoint;
        v_flex()
            .gap_2()
            .children(rows)
            .child(
                h_flex()
                    .gap_2()
                    .child(div().w(px(140.)).child(Input::new(name).small()))
                    .child(div().flex_1().child(Input::new(base).small()))
                    .child(div().w(px(200.)).child(Input::new(key).small().mask_toggle()))
                    .child(
                        Button::new("add-endpoint")
                            .small()
                            .outline()
                            .icon(IconName::Plus)
                            .label("Add")
                            .on_click(cx.listener(|this, _, window, cx| this.add_endpoint(window, cx))),
                    ),
            )
            .into_any_element()
    }

    fn render_keys(&self, overview: &Value, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        let rows =
            overview["providers"].as_array().cloned().unwrap_or_default().into_iter().enumerate().map(|(ix, p)| {
                let id = text(&p, "id");
                let connected = flag(&p, "connected");
                let typing =
                    self.key_entry.as_ref().filter(|(provider, _)| *provider == id).map(|(_, field)| field.clone());
                let mut row = ui::card(&theme).justify_between().child(
                    h_flex()
                        .gap_3()
                        .child(ui::dot(if connected { theme.success } else { theme.muted_foreground }))
                        .child(div().text_sm().font_medium().child(id.clone()))
                        .child(div().text_xs().text_color(theme.muted_foreground).child(if connected {
                            "key saved"
                        } else {
                            "no key"
                        })),
                );
                row = match typing {
                    Some(field) => row.child(
                        h_flex()
                            .gap_2()
                            .child(div().w(px(280.)).child(Input::new(&field).small().mask_toggle()))
                            .child(Button::new(("save-key", ix)).small().primary().label("Save").on_click(
                                cx.listener(move |this, _, _, cx| {
                                    let key = field.read(cx).value().trim().to_string();
                                    let provider = id.clone();
                                    this.key_entry = None;
                                    if !key.is_empty() {
                                        this.write(
                                            format!("key {provider}"),
                                            move |api| {
                                                // Checked first, as the web page does, so a mistyped key isn't kept.
                                                let check = api.post(
                                                    "/credentials/validate-key",
                                                    json!({ "provider_id": provider, "api_key": key }),
                                                )?;
                                                if check["valid"] == Value::Bool(false) {
                                                    anyhow::bail!(
                                                        "{provider} didn't accept that key: {}",
                                                        text(&check, "message")
                                                    );
                                                }
                                                api.post(
                                                    "/credentials",
                                                    json!({ "credential_id": provider, "keys": { "api_key": key } }),
                                                )
                                            },
                                            cx,
                                        );
                                    }
                                }),
                            )),
                    ),
                    None if connected => {
                        row.child(Button::new(("remove-key", ix)).small().ghost().label("Remove key").on_click(
                            cx.listener(move |this, _, _, cx| {
                                let provider = id.clone();
                                this.write(
                                    format!("key {provider}"),
                                    move |api| api.delete(&format!("/credentials/{provider}")),
                                    cx,
                                )
                            }),
                        ))
                    }
                    None => row.child(Button::new(("add-key", ix)).small().outline().label("Add key").on_click(
                        cx.listener(move |this, _, window, cx| {
                            let field = cx.new(|cx| InputState::new(window, cx).placeholder("API key").masked(true));
                            field.update(cx, |s, cx| s.focus(window, cx));
                            this.key_entry = Some((id.clone(), field));
                            cx.notify();
                        }),
                    )),
                };
                row
            });
        v_flex().gap_2().children(rows).into_any_element()
    }

    fn render_saved(&self, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        if self.library.is_empty() {
            return ui::muted("None yet. Save a setup from the web dashboard's Advanced section.", &theme)
                .into_any_element();
        }
        let rows = self.library.iter().enumerate().map(|(ix, (name, setup))| {
            let confirming = self.confirm_delete.as_deref() == Some(name.as_str());
            let name = name.clone();
            ui::card(&theme)
                .justify_between()
                .child(
                    v_flex()
                        .min_w_0()
                        .child(
                            h_flex()
                                .gap_2()
                                .child(div().text_sm().font_medium().child(name.clone()))
                                .when(is_judge(setup), |row| {
                                    row.child(div().text_xs().text_color(theme.muted_foreground).child("judge"))
                                }),
                        )
                        .child(
                            h_flex()
                                .gap_2()
                                .text_xs()
                                .text_color(theme.muted_foreground)
                                .when_some(key_note(setup), |row, note| {
                                    row.child(Icon::new(IconName::KeyRound).xsmall()).child(note)
                                })
                                .child(div().truncate().child(format!(
                                    "{} · {}",
                                    text(setup, "model"),
                                    text(setup, "api_base")
                                ))),
                        ),
                )
                .child(
                    Button::new(("del-setup", ix))
                        .small()
                        .ghost()
                        .when(confirming, |b| b.danger().label("Delete for good"))
                        .when(!confirming, |b| b.icon(IconName::Trash).tooltip("Delete"))
                        .on_click(cx.listener(move |this, _, _, cx| {
                            if this.confirm_delete.as_deref() == Some(name.as_str()) {
                                this.confirm_delete = None;
                                let name = name.clone();
                                this.write(
                                    format!("setup {name}"),
                                    move |api| {
                                        api.put("/config/provider-library", json!({ "name": name, "section": null }))
                                    },
                                    cx,
                                );
                            } else {
                                this.confirm_delete = Some(name.clone());
                                cx.notify();
                            }
                        })),
                )
        });
        v_flex().gap_2().children(rows).into_any_element()
    }

    fn render_subscriptions(&self, overview: &Value, cx: &mut Context<Self>) -> Option<AnyElement> {
        let detected: Vec<Value> = overview["subscriptions"]
            .as_array()
            .into_iter()
            .flatten()
            .filter(|s| flag(s, "detected"))
            .cloned()
            .collect();
        if detected.is_empty() {
            return None;
        }
        let theme = cx.theme().clone();
        let rows = detected.into_iter().enumerate().map(|(ix, s)| {
            let id = text(&s, "id");
            ui::card(&theme)
                .justify_between()
                .child(
                    v_flex()
                        .min_w_0()
                        .child(div().text_sm().font_medium().child(text(&s, "name")))
                        .child(div().text_xs().text_color(theme.muted_foreground).child(text(&s, "description"))),
                )
                .child(if flag(&s, "active") {
                    div().text_xs().text_color(theme.success).child("In use").into_any_element()
                } else {
                    Button::new(("use-sub", ix))
                        .small()
                        .outline()
                        .label("Use as the main model")
                        .on_click(cx.listener(move |this, _, _, cx| {
                            let id = id.clone();
                            this.write(
                                "llm".into(),
                                move |api| api.put("/config/llm", json!({ "subscription": id })),
                                cx,
                            )
                        }))
                        .into_any_element()
                })
        });
        Some(
            v_flex()
                .gap_2()
                .child(div().px_3().py_2().rounded_md().bg(theme.muted).text_xs().child(
                    "Using a subscription outside its own app is at your own risk; the provider may not allow it.",
                ))
                .children(rows)
                .into_any_element(),
        )
    }
}

impl Render for ModelsPage {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let theme = cx.theme().clone();
        let (header, body) = ui::page(
            "models-body",
            "Models",
            "Which model each role thinks with, and where those models come from.",
            &theme,
        );
        let header = header.child(
            h_flex().pt_2().child(
                Button::new("refresh")
                    .small()
                    .ghost()
                    .icon(IconName::RefreshCw)
                    .label("Refresh")
                    .on_click(cx.listener(|this, _, _, cx| this.load(cx))),
            ),
        );
        let content = match self.overview.clone() {
            None => v_flex().p_8().child(Spinner::new()),
            Some(Err(e)) => v_flex().p_8().child(ui::error_line(format!("Couldn't load models: {e}"), &theme)),
            Some(Ok(overview)) => {
                let queens: Vec<Value> = overview["queens"].as_array().cloned().unwrap_or_default();
                v_flex()
                    .gap_8()
                    .px_8()
                    .py_6()
                    .w_full()
                    .max_w(px(880.))
                    .mx_auto()
                    .when_some(self.error.clone(), |col, e| col.child(ui::error_line(e, &theme)))
                    .child(ui::section("In use", &theme).child(self.render_roles(&overview, cx)))
                    .when(!queens.is_empty(), |col| {
                        col.child(ui::section("Queens with their own model", &theme).children(queens.iter().map(|q| {
                            ui::card(&theme)
                                .justify_between()
                                .child(div().text_sm().font_medium().child(text(q, "name")))
                                .child(div().text_sm().text_color(theme.muted_foreground).child(summary(q)))
                        })))
                    })
                    .child(ui::section("Endpoints", &theme).child(self.render_endpoints(&overview, cx)))
                    .child(ui::section("API keys", &theme).child(self.render_keys(&overview, cx)))
                    .child(ui::section("Saved setups", &theme).child(self.render_saved(cx)))
                    .when_some(self.render_subscriptions(&overview, cx), |col, subs| {
                        col.child(ui::section("Subscriptions", &theme).child(subs))
                    })
            }
        };
        v_flex().size_full().child(header).child(body.child(content))
    }
}
