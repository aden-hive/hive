//! What the queens remember: global memories and each queen's own, readable and editable as the
//! files they are. Mirrors `frontend/src/pages/memory-library.tsx`.

use gpui_kit::assets::IconName;
use gpui_kit::base::{Disableable as _, Selectable as _, h_flex, v_flex};
use gpui_kit::component::button::{Button, ButtonVariants as _};
use gpui_kit::component::input::{Input, InputState, Textarea, TextareaState};
use gpui_kit::component::spinner::Spinner;
use gpui_kit::component::{ActiveTheme as _, Sizable as _, StyledExt as _};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;
use serde_json::{Value, json};

use super::text;
use crate::api::{api, encode};
use crate::{bg, ui};

/// Which memories the list shows; colony and agent memories stay out of it, as on the web.
#[derive(Clone, PartialEq)]
enum Scope {
    Global,
    Queen(String),
}

/// The memory opened for reading or editing.
struct Opened {
    path: String,
    /// The file as loaded, to tell whether the editor holds changes.
    original: Option<String>,
    editor: Entity<TextareaState>,
    error: Option<String>,
    confirm_delete: bool,
}

pub struct MemoryPage {
    memories: Option<Result<Vec<Value>, String>>,
    scope: Scope,
    search: Entity<InputState>,
    opened: Option<Opened>,
    saving: bool,
    tasks: Vec<Task<()>>,
}

/// A memory's display name: its `name`, else the filename without `.md`.
fn title(memory: &Value) -> String {
    let name = text(memory, "name");
    if name.is_empty() { text(memory, "filename").trim_end_matches(".md").replace(['_', '-'], " ") } else { name }
}

impl MemoryPage {
    pub fn new(window: &mut Window, cx: &mut Context<Self>) -> Self {
        let search = cx.new(|cx| InputState::new(window, cx).placeholder("Search memories"));
        cx.observe(&search, |_, _, cx| cx.notify()).detach();
        let mut page =
            Self { memories: None, scope: Scope::Global, search, opened: None, saving: false, tasks: Vec::new() };
        page.load(cx);
        page
    }

    fn load(&mut self, cx: &mut Context<Self>) {
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || api.get("/memories"),
            |this: &mut Self, loaded, _| {
                this.memories = Some(
                    loaded.map(|b| b["memories"].as_array().cloned().unwrap_or_default()).map_err(|e| e.to_string()),
                )
            },
        ));
    }

    fn open(&mut self, path: String, window: &mut Window, cx: &mut Context<Self>) {
        if self.opened.as_ref().is_some_and(|o| o.path == path) {
            self.opened = None;
            cx.notify();
            return;
        }
        let editor = cx.new(|cx| TextareaState::new(window, cx).auto_grow(6, 28));
        cx.observe(&editor, |_, _, cx| cx.notify()).detach();
        self.opened = Some(Opened { path: path.clone(), original: None, editor, error: None, confirm_delete: false });
        let api = api(cx);
        let query = encode(&path);
        self.tasks.push(bg::spawn_in(
            window,
            cx,
            move || api.get(&format!("/memories/file?path={query}")),
            move |this: &mut Self, file, window, cx| {
                let Some(opened) = this.opened.as_mut().filter(|o| o.path == path) else { return };
                match file {
                    Ok(file) => {
                        let content = text(&file, "content");
                        opened.editor.update(cx, |state, cx| state.set_value(content.clone(), window, cx));
                        opened.original = Some(content);
                    }
                    Err(e) => opened.error = Some(e.to_string()),
                }
            },
        ));
        cx.notify();
    }

    fn save(&mut self, cx: &mut Context<Self>) {
        let Some(opened) = self.opened.as_mut() else { return };
        let content = opened.editor.read(cx).value().to_string();
        let path = opened.path.clone();
        self.saving = true;
        let api = api(cx);
        let saved_content = content.clone();
        self.tasks.push(bg::spawn(
            cx,
            move || api.put(&format!("/memories/file?path={}", encode(&path)), json!({ "content": content })),
            move |this: &mut Self, saved, cx| {
                this.saving = false;
                if let Some(opened) = this.opened.as_mut() {
                    match saved {
                        Ok(_) => {
                            opened.original = Some(saved_content);
                            opened.error = None;
                            this.load(cx);
                        }
                        Err(e) => opened.error = Some(e.to_string()),
                    }
                }
            },
        ));
        cx.notify();
    }

    fn delete(&mut self, cx: &mut Context<Self>) {
        let Some(opened) = self.opened.as_mut() else { return };
        if !opened.confirm_delete {
            opened.confirm_delete = true;
            cx.notify();
            return;
        }
        let path = opened.path.clone();
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || api.delete(&format!("/memories/file?path={}", encode(&path))),
            |this: &mut Self, deleted, cx| match deleted {
                Ok(_) => {
                    this.opened = None;
                    this.load(cx);
                }
                Err(e) => {
                    if let Some(opened) = this.opened.as_mut() {
                        opened.error = Some(e.to_string());
                    }
                }
            },
        ));
    }

    fn render_opened(&self, opened: &Opened, cx: &mut Context<Self>) -> AnyElement {
        let theme = cx.theme().clone();
        let dirty = opened.original.as_deref().is_some_and(|o| o != opened.editor.read(cx).value().as_ref());
        v_flex()
            .gap_2()
            .p_3()
            .rounded_lg()
            .border_1()
            .border_color(theme.border)
            .bg(theme.sidebar)
            .when_some(opened.error.clone(), |col, e| col.child(ui::error_line(e, &theme)))
            .child(if opened.original.is_none() && opened.error.is_none() {
                Spinner::new().small().into_any_element()
            } else {
                Textarea::new(&opened.editor).into_any_element()
            })
            .child(
                h_flex()
                    .gap_2()
                    .justify_end()
                    .child(
                        Button::new("delete")
                            .small()
                            .ghost()
                            .when(opened.confirm_delete, |b| b.danger().label("Delete this memory for good"))
                            .when(!opened.confirm_delete, |b| b.icon(IconName::Trash).label("Delete"))
                            .on_click(cx.listener(|this, _, _, cx| this.delete(cx))),
                    )
                    .child(
                        Button::new("save")
                            .small()
                            .primary()
                            .label("Save")
                            .loading(self.saving)
                            .disabled(!dirty)
                            .on_click(cx.listener(|this, _, _, cx| this.save(cx))),
                    ),
            )
            .into_any_element()
    }
}

impl Render for MemoryPage {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let theme = cx.theme().clone();
        let (header, body) = ui::page(
            "memory-body",
            "Memory",
            "What the queens remember across chats. Each memory is a file; edit it as one.",
            &theme,
        );
        let memories = match &self.memories {
            None => return v_flex().size_full().child(header).child(body.child(v_flex().p_8().child(Spinner::new()))),
            Some(Err(e)) => {
                return v_flex().size_full().child(header).child(
                    body.child(v_flex().p_8().child(ui::error_line(format!("Couldn't load memories: {e}"), &theme))),
                );
            }
            Some(Ok(memories)) => memories.clone(),
        };

        let mut queens: Vec<String> =
            memories.iter().filter(|m| text(m, "scope") == "queen").map(|m| text(m, "scope_name")).collect();
        queens.sort();
        queens.dedup();
        let query = self.search.read(cx).value().to_lowercase();
        let shown: Vec<Value> = memories
            .into_iter()
            .filter(|m| match &self.scope {
                Scope::Global => text(m, "scope") == "global",
                Scope::Queen(q) => text(m, "scope") == "queen" && &text(m, "scope_name") == q,
            })
            .filter(|m| {
                query.is_empty()
                    || [title(m), text(m, "filename"), text(m, "description")]
                        .iter()
                        .any(|s| s.to_lowercase().contains(&query))
            })
            .collect();

        let scopes = h_flex()
            .gap_1()
            .flex_wrap()
            .child(
                Button::new("scope-global")
                    .small()
                    .ghost()
                    .label("Global")
                    .selected(self.scope == Scope::Global)
                    .on_click(cx.listener(|this, _, _, cx| {
                        this.scope = Scope::Global;
                        cx.notify();
                    })),
            )
            .children(queens.into_iter().enumerate().map(|(ix, q)| {
                let scope = Scope::Queen(q.clone());
                Button::new(("scope", ix)).small().ghost().label(q).selected(self.scope == scope).on_click(cx.listener(
                    move |this, _, _, cx| {
                        this.scope = scope.clone();
                        cx.notify();
                    },
                ))
            }));

        let rows: Vec<AnyElement> = shown
            .iter()
            .enumerate()
            .map(|(ix, m)| {
                let path = text(m, "path");
                let is_open = self.opened.as_ref().is_some_and(|o| o.path == path);
                let mut row = v_flex().gap_2().child(
                    ui::card(&theme)
                        .id(("memory", ix))
                        .cursor_pointer()
                        .hover(|row| row.bg(theme.list_hover))
                        .child(
                            v_flex()
                                .min_w_0()
                                .flex_1()
                                .child(h_flex().gap_2().child(div().text_sm().font_medium().child(title(m))).when(
                                    !text(m, "type").is_empty(),
                                    |row| {
                                        row.child(
                                            div().text_xs().text_color(theme.muted_foreground).child(text(m, "type")),
                                        )
                                    },
                                ))
                                .when(!text(m, "description").is_empty(), |col| {
                                    col.child(
                                        div()
                                            .text_sm()
                                            .text_color(theme.muted_foreground)
                                            .child(text(m, "description")),
                                    )
                                }),
                        )
                        .when_some(m["mtime"].as_f64(), |row, t| {
                            row.child(div().text_xs().text_color(theme.muted_foreground).child(ui::ago(t)))
                        })
                        .on_click(cx.listener(move |this, _, window, cx| this.open(path.clone(), window, cx))),
                );
                if is_open && let Some(opened) = &self.opened {
                    row = row.child(self.render_opened(opened, cx));
                }
                row.into_any_element()
            })
            .collect();

        let content = v_flex()
            .gap_4()
            .px_8()
            .py_6()
            .w_full()
            .max_w(px(880.))
            .mx_auto()
            .child(
                h_flex().gap_3().child(div().w(px(320.)).child(Input::new(&self.search).small())).child(
                    Button::new("refresh")
                        .small()
                        .ghost()
                        .icon(IconName::RefreshCw)
                        .on_click(cx.listener(|this, _, _, cx| this.load(cx))),
                ),
            )
            .child(scopes)
            .child(if rows.is_empty() {
                ui::muted("No memories here.", &theme).into_any_element()
            } else {
                v_flex().gap_2().children(rows).into_any_element()
            });
        v_flex().size_full().child(header).child(body.child(content))
    }
}
