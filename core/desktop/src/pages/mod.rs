//! The library and settings pages, one view each, built the first time they're opened.

mod claude_code;
mod credentials;
mod home;
mod memory;
mod models;
mod org_chart;
mod profile;
mod prompts;
mod settings;
mod skills;
mod tools;

use gpui_kit::*;
use serde_json::Value;

use crate::shell::{Page, Shell};

/// A field as text: strings as they are, numbers written out, anything missing as "".
pub(crate) fn text(value: &Value, key: &str) -> String {
    match &value[key] {
        Value::String(s) => s.clone(),
        Value::Null => String::new(),
        other => other.to_string(),
    }
}

pub(crate) fn flag(value: &Value, key: &str) -> bool {
    value[key].as_bool().unwrap_or(false)
}

pub fn build(page: Page, shell: WeakEntity<Shell>, window: &mut Window, cx: &mut App) -> AnyView {
    match page {
        Page::Home => cx.new(|cx| home::HomePage::new(shell, window, cx)).into(),
        Page::OrgChart => cx.new(|cx| org_chart::OrgChartPage::new(shell, window, cx)).into(),
        Page::Credentials => cx.new(|cx| credentials::CredentialsPage::new(window, cx)).into(),
        Page::Prompts => cx.new(|cx| prompts::PromptsPage::new(shell, window, cx)).into(),
        Page::Models => cx.new(|cx| models::ModelsPage::new(window, cx)).into(),
        Page::Memory => cx.new(|cx| memory::MemoryPage::new(window, cx)).into(),
        Page::Skills => cx.new(|cx| skills::SkillsPage::new(window, cx)).into(),
        Page::Tools => cx.new(|cx| tools::ToolsPage::new(window, cx)).into(),
        Page::Settings => cx.new(|cx| settings::SettingsPage::new(window, cx)).into(),
    }
}

/// The read-only page of the Claude Code queen with this id.
pub fn claude_code(queen_id: String, window: &mut Window, cx: &mut App) -> AnyView {
    cx.new(|cx| claude_code::ClaudeCodePage::new(queen_id, window, cx)).into()
}

/// The profile page of the queen with this id.
pub fn profile(queen_id: String, shell: WeakEntity<Shell>, window: &mut Window, cx: &mut App) -> AnyView {
    cx.new(|cx| profile::ProfilePage::new(queen_id, shell, window, cx)).into()
}
