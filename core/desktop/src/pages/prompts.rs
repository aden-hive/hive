//! The user's own prompts: write them, find them, copy them, and start a chat with one. Mirrors
//! the "My prompts" half of `frontend/src/pages/prompt-library.tsx`; the featured catalog lives
//! in the cloud.

use gpui_kit::assets::IconName;
use gpui_kit::base::{Selectable as _, h_flex, v_flex};
use gpui_kit::component::button::{Button, ButtonVariants as _};
use gpui_kit::component::input::{Input, InputState, Textarea, TextareaState};
use gpui_kit::component::spinner::Spinner;
use gpui_kit::component::{ActiveTheme as _, Sizable as _, StyledExt as _};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;
use serde_json::{Value, json};

use super::home::queen_chips;
use super::text;
use crate::api::{Queen, api, encode};
use crate::shell::Shell;
use crate::{bg, ui};

/// The categories a prompt can be filed under (`promptCategories` in `data/prompts.ts`).
const CATEGORIES: [(&str, &str); 11] = [
    ("marketing", "Marketing & Growth"),
    ("sales", "Sales & Business Development"),
    ("support", "Customer Success & Support"),
    ("product", "Product & Engineering"),
    ("finance", "Finance & Accounting"),
    ("hr", "HR & People Operations"),
    ("legal", "Legal & Compliance"),
    ("operations", "Operations & Supply Chain"),
    ("data", "Data & Analytics"),
    ("executive", "Executive & Administrative"),
    ("security", "IT & Security"),
];

/// The queen a category's prompts go to unless the user picks another (`categoryToQueen`).
pub(super) fn queen_for_category(category: &str) -> Option<&'static str> {
    Some(match category {
        "marketing" => "queen_growth",
        "sales" => "queen_outbound",
        "product" => "queen_product_strategy",
        "data" | "security" => "queen_technology",
        "finance" => "queen_finance_fundraising",
        "hr" => "queen_talent",
        "legal" => "queen_legal",
        "operations" | "support" | "executive" => "queen_operations",
        _ => return None,
    })
}

fn category_label(category: &str) -> String {
    match CATEGORIES.iter().find(|(id, _)| *id == category) {
        Some((_, name)) => name.to_string(),
        None if category.is_empty() || category == "custom" => "Custom".into(),
        None => category.to_string(),
    }
}

/// The prompt form, for a new prompt or one being edited.
struct Editor {
    /// The prompt being edited; `None` for a new one.
    id: Option<String>,
    title: Entity<InputState>,
    /// A key of [`CATEGORIES`], or "" for Custom.
    category: String,
    content: Entity<TextareaState>,
    error: Option<String>,
    saving: bool,
}

pub struct PromptsPage {
    shell: WeakEntity<Shell>,
    prompts: Option<Result<Vec<Value>, String>>,
    search: Entity<InputState>,
    editor: Option<Editor>,
    /// The prompt whose "Send to" picker is open.
    using: Option<String>,
    /// A prompt the user asked to delete; a second click confirms.
    confirm_delete: Option<String>,
    /// The prompt whose content was just copied, so its button can say so.
    copied: Option<String>,
    /// A failed delete, by prompt id.
    row_error: Option<(String, String)>,
    tasks: Vec<Task<()>>,
}

impl PromptsPage {
    pub fn new(shell: WeakEntity<Shell>, window: &mut Window, cx: &mut Context<Self>) -> Self {
        let search = cx.new(|cx| InputState::new(window, cx).placeholder("Search prompts"));
        cx.observe(&search, |_, _, cx| cx.notify()).detach();
        let mut page = Self {
            shell,
            prompts: None,
            search,
            editor: None,
            using: None,
            confirm_delete: None,
            copied: None,
            row_error: None,
            tasks: Vec::new(),
        };
        page.load(cx);
        page
    }

    fn load(&mut self, cx: &mut Context<Self>) {
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || api.get("/prompts"),
            |this: &mut Self, loaded, _| {
                this.prompts = Some(
                    loaded.map(|b| b["prompts"].as_array().cloned().unwrap_or_default()).map_err(|e| e.to_string()),
                )
            },
        ));
    }

    fn queens(&self, cx: &App) -> Vec<Queen> {
        self.shell.upgrade().map(|s| s.read(cx).queens().to_vec()).unwrap_or_default()
    }

    /// Open the form, empty or filled with `prompt`.
    fn edit(&mut self, prompt: Option<&Value>, window: &mut Window, cx: &mut Context<Self>) {
        let title = cx.new(|cx| InputState::new(window, cx).placeholder("Title, e.g. Weekly report"));
        let content =
            cx.new(|cx| TextareaState::new(window, cx).auto_grow(6, 20).placeholder("What should the queen do?"));
        cx.observe(&title, |_, _, cx| cx.notify()).detach();
        cx.observe(&content, |_, _, cx| cx.notify()).detach();
        let mut category = String::new();
        if let Some(prompt) = prompt {
            let (t, c) = (text(prompt, "title"), text(prompt, "content"));
            title.update(cx, |s, cx| s.set_value(t, window, cx));
            content.update(cx, |s, cx| s.set_value(c, window, cx));
            category = text(prompt, "category");
            if !CATEGORIES.iter().any(|(id, _)| *id == category) {
                category.clear();
            }
        }
        title.update(cx, |s, cx| s.focus(window, cx));
        self.editor =
            Some(Editor { id: prompt.map(|p| text(p, "id")), title, category, content, error: None, saving: false });
        self.using = None;
        cx.notify();
    }

    fn save(&mut self, cx: &mut Context<Self>) {
        let Some(editor) = self.editor.as_mut() else { return };
        let title = editor.title.read(cx).value().trim().to_string();
        let content = editor.content.read(cx).value().trim().to_string();
        if title.is_empty() || content.is_empty() {
            editor.error = Some("A prompt needs a title and some content.".into());
            cx.notify();
            return;
        }
        editor.saving = true;
        editor.error = None;
        let id = editor.id.clone();
        let category = editor.category.clone();
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            move || match id {
                Some(id) => api.patch(
                    &format!("/prompts/{}", encode(&id)),
                    json!({ "title": title, "category": category, "content": content }),
                ),
                None => api.post(
                    "/prompts",
                    json!({ "title": title, "category": category, "content": content, "skills": [] }),
                ),
            },
            |this: &mut Self, saved, cx| match saved {
                Ok(_) => {
                    this.editor = None;
                    this.load(cx);
                }
                Err(e) => {
                    if let Some(editor) = this.editor.as_mut() {
                        editor.saving = false;
                        editor.error = Some(e.to_string());
                    }
                }
            },
        ));
        cx.notify();
    }

    fn delete(&mut self, id: String, cx: &mut Context<Self>) {
        if self.confirm_delete.as_deref() != Some(id.as_str()) {
            self.confirm_delete = Some(id);
            cx.notify();
            return;
        }
        self.confirm_delete = None;
        self.row_error = None;
        let api = api(cx);
        self.tasks.push(bg::spawn(
            cx,
            {
                let id = id.clone();
                move || api.delete(&format!("/prompts/{}", encode(&id)))
            },
            move |this: &mut Self, deleted, cx| match deleted {
                Ok(_) => this.load(cx),
                Err(e) => this.row_error = Some((id, e.to_string())),
            },
        ));
    }

    fn render_editor(&self, editor: &Editor, cx: &mut Context<Self>) -> AnyElement {
        let categories = std::iter::once(("", "Custom")).chain(CATEGORIES).enumerate().map(|(ix, (id, name))| {
            Button::new(("category", ix)).small().ghost().label(name).selected(editor.category == id).on_click(
                cx.listener(move |this, _, _, cx| {
                    if let Some(editor) = this.editor.as_mut() {
                        editor.category = id.to_string();
                        cx.notify();
                    }
                }),
            )
        });
        let categories: Vec<_> = categories.collect();
        let theme = cx.theme().clone();
        v_flex()
            .gap_3()
            .p_4()
            .rounded_lg()
            .border_1()
            .border_color(theme.border)
            .bg(theme.sidebar)
            .child(div().text_sm().font_semibold().child(if editor.id.is_some() {
                "Edit prompt"
            } else {
                "New prompt"
            }))
            .child(Input::new(&editor.title).small())
            .child(
                v_flex()
                    .gap_1()
                    .child(div().text_xs().text_color(theme.muted_foreground).child("Category"))
                    .child(h_flex().gap_1().flex_wrap().children(categories)),
            )
            .child(Textarea::new(&editor.content))
            .when_some(editor.error.clone(), |col, e| col.child(ui::error_line(e, &theme)))
            .child(
                h_flex()
                    .gap_2()
                    .justify_end()
                    .child(Button::new("cancel-edit").small().ghost().label("Cancel").on_click(cx.listener(
                        |this, _, _, cx| {
                            this.editor = None;
                            cx.notify();
                        },
                    )))
                    .child(
                        Button::new("save-prompt")
                            .small()
                            .primary()
                            .label("Save")
                            .loading(editor.saving)
                            .on_click(cx.listener(|this, _, _, cx| this.save(cx))),
                    ),
            )
            .into_any_element()
    }

    fn render_prompt(&self, ix: usize, prompt: &Value, queens: &[Queen], cx: &mut Context<Self>) -> AnyElement {
        let id = text(prompt, "id");
        let content = text(prompt, "content");
        let category = text(prompt, "category");
        let confirming = self.confirm_delete.as_deref() == Some(id.as_str());
        let copied = self.copied.as_deref() == Some(id.as_str());
        let using = self.using.as_deref() == Some(id.as_str());

        let picker = using.then(|| {
            // The category's queen comes first, as the one the web would send it to.
            let suggested = queen_for_category(&category);
            let mut ordered: Vec<Queen> = queens.to_vec();
            ordered.sort_by_key(|q| Some(q.id.as_str()) != suggested);
            let content = content.clone();
            queen_chips("use-queen", &ordered, suggested, cx, move |this: &mut Self, queen, window, cx| {
                this.using = None;
                let (queen_id, content) = (queen.id.clone(), content.clone());
                this.shell.update(cx, |shell, cx| shell.chat_with(&queen_id, content, true, window, cx)).ok();
            })
        });

        let copy = Button::new(("copy", ix))
            .small()
            .ghost()
            .icon(if copied { IconName::Check } else { IconName::Copy })
            .tooltip(if copied { "Copied" } else { "Copy the prompt" })
            .on_click(cx.listener({
                let (id, content) = (id.clone(), content.clone());
                move |this, _, _, cx| {
                    cx.write_to_clipboard(ClipboardItem::new_string(content.clone()));
                    this.copied = Some(id.clone());
                    cx.notify();
                }
            }));
        let edit =
            Button::new(("edit", ix)).small().ghost().icon(IconName::Pencil).tooltip("Edit").on_click(cx.listener({
                let prompt = prompt.clone();
                move |this, _, window, cx| this.edit(Some(&prompt), window, cx)
            }));
        let delete = Button::new(("delete", ix))
            .small()
            .ghost()
            .when(confirming, |b| b.danger().label("Delete for good"))
            .when(!confirming, |b| b.icon(IconName::Trash).tooltip("Delete"))
            .on_click(cx.listener({
                let id = id.clone();
                move |this, _, _, cx| this.delete(id.clone(), cx)
            }));
        let use_button =
            Button::new(("use", ix)).small().outline().icon(IconName::Send).label("Use").selected(using).on_click(
                cx.listener({
                    let id = id.clone();
                    move |this, _, _, cx| {
                        this.using = if this.using.as_deref() == Some(id.as_str()) { None } else { Some(id.clone()) };
                        cx.notify();
                    }
                }),
            );

        let theme = cx.theme().clone();
        let row_error = self.row_error.as_ref().filter(|(failed, _)| *failed == id).map(|(_, e)| e.clone());
        v_flex()
            .gap_2()
            .px_4()
            .py_3()
            .rounded_lg()
            .border_1()
            .border_color(theme.border)
            .bg(theme.background)
            .child(
                h_flex()
                    .gap_3()
                    .justify_between()
                    .child(
                        v_flex()
                            .min_w_0()
                            .flex_1()
                            .child(
                                h_flex()
                                    .gap_2()
                                    .child(div().text_sm().font_medium().truncate().child(text(prompt, "title")))
                                    .child(
                                        div()
                                            .text_xs()
                                            .text_color(theme.muted_foreground)
                                            .child(category_label(&category)),
                                    ),
                            )
                            .child(
                                div()
                                    .text_sm()
                                    .text_color(theme.muted_foreground)
                                    .child(ui::clip(&content.replace('\n', " "), 220)),
                            ),
                    )
                    .child(h_flex().gap_1().flex_shrink_0().child(copy).child(edit).child(delete).child(use_button)),
            )
            .when_some(row_error, |col, e| col.child(ui::error_line(e, &theme)))
            .when_some(picker, |col, picker| {
                col.child(
                    v_flex()
                        .gap_2()
                        .pt_2()
                        .border_t_1()
                        .border_color(theme.border)
                        .child(div().text_xs().text_color(theme.muted_foreground).child("Send it to a new chat with:"))
                        .child(if queens.is_empty() {
                            ui::muted("No queens yet.", &theme).into_any_element()
                        } else {
                            picker.into_any_element()
                        }),
                )
            })
            .into_any_element()
    }
}

impl Render for PromptsPage {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let theme = cx.theme().clone();
        let (header, body) =
            ui::page("prompts-body", "Prompts", "Prompts you've written, ready to send to a queen.", &theme);
        let prompts = match &self.prompts {
            None => return v_flex().size_full().child(header).child(body.child(v_flex().p_8().child(Spinner::new()))),
            Some(Err(e)) => {
                return v_flex().size_full().child(header).child(
                    body.child(v_flex().p_8().child(ui::error_line(format!("Couldn't load prompts: {e}"), &theme))),
                );
            }
            Some(Ok(prompts)) => prompts.clone(),
        };
        let query = self.search.read(cx).value().to_lowercase();
        let queens = self.queens(cx);
        let editing = self.editor.as_ref().and_then(|e| e.id.clone());

        // Newest first; the server appends.
        let mut rows = Vec::new();
        for (ix, prompt) in prompts.iter().rev().enumerate() {
            let haystack = [text(prompt, "title"), text(prompt, "content"), category_label(&text(prompt, "category"))];
            if !query.is_empty() && !haystack.iter().any(|s| s.to_lowercase().contains(&query)) {
                continue;
            }
            match &self.editor {
                Some(editor) if editing.as_deref() == Some(text(prompt, "id").as_str()) => {
                    rows.push(self.render_editor(editor, cx))
                }
                _ => rows.push(self.render_prompt(ix, prompt, &queens, cx)),
            }
        }
        let new_editor = self.editor.as_ref().filter(|e| e.id.is_none()).map(|editor| self.render_editor(editor, cx));
        let empty = if prompts.is_empty() {
            "No prompts yet. Write one to reuse it later."
        } else {
            "No prompts match that search."
        };

        let content = v_flex()
            .gap_4()
            .px_8()
            .py_6()
            .w_full()
            .max_w(px(880.))
            .mx_auto()
            .child(
                h_flex()
                    .gap_3()
                    .child(div().w(px(320.)).child(Input::new(&self.search).small()))
                    .child(
                        Button::new("refresh")
                            .small()
                            .ghost()
                            .icon(IconName::RefreshCw)
                            .tooltip("Refresh")
                            .on_click(cx.listener(|this, _, _, cx| this.load(cx))),
                    )
                    .child(div().flex_1())
                    .child(
                        Button::new("new-prompt")
                            .small()
                            .primary()
                            .icon(IconName::Plus)
                            .label("New prompt")
                            .on_click(cx.listener(|this, _, window, cx| this.edit(None, window, cx))),
                    ),
            )
            .when(rows.is_empty() && !(prompts.is_empty() && new_editor.is_some()), |col| {
                col.child(ui::muted(empty, &theme))
            })
            .children(new_editor)
            .when(!rows.is_empty(), |col| col.child(v_flex().gap_2().children(rows)));
        v_flex().size_full().child(header).child(body.child(content))
    }
}
