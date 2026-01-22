/**
 * Settings Store
 *
 * Zustand store for persisted UI settings.
 * - Initializes from LocalStorage on creation
 * - Auto-syncs to LocalStorage on every change
 * - Server sync is handled by useSettings hooks
 */

import { create } from 'zustand'
import type { UISettings, TimeRange } from '@/types/settings'
import { DEFAULT_UI_SETTINGS } from '@/types/settings'

const STORAGE_KEY = 'honeycomb_ui_settings'

// =============================================================================
// LocalStorage Helpers
// =============================================================================

/**
 * Read settings from LocalStorage
 * Returns defaults if not found or on error
 */
function getLocalSettings(): UISettings {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      return { ...DEFAULT_UI_SETTINGS, ...JSON.parse(stored) }
    }
  } catch (e: unknown) {
    console.warn('[SettingsStore] Failed to parse local settings:', e)
  }
  return DEFAULT_UI_SETTINGS
}

/**
 * Write settings to LocalStorage
 * Merges with existing settings
 */
function setLocalSettings(settings: Partial<UISettings>): void {
  try {
    const current = getLocalSettings()
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...current, ...settings }))
  } catch (e: unknown) {
    console.warn('[SettingsStore] Failed to save local settings:', e)
  }
}

// =============================================================================
// Store Types
// =============================================================================

interface SettingsState {
  // Settings values
  sidebarCollapsed: boolean
  performanceDashboardTimeRange: TimeRange

  // Loading/sync state
  isLoaded: boolean
  isSyncing: boolean

  // Actions
  setSidebarCollapsed: (collapsed: boolean) => void
  setPerformanceDashboardTimeRange: (range: TimeRange) => void
  loadSettings: (settings: UISettings) => void
  setIsSyncing: (syncing: boolean) => void
}

// =============================================================================
// Store
// =============================================================================

// Initialize from LocalStorage on store creation
const initial = getLocalSettings()

export const useSettingsStore = create<SettingsState>((set) => ({
  // Initial values from LocalStorage
  sidebarCollapsed: initial.sidebarCollapsed,
  performanceDashboardTimeRange: initial.performanceDashboardTimeRange,
  isLoaded: false,
  isSyncing: false,

  setSidebarCollapsed: (collapsed) => {
    set({ sidebarCollapsed: collapsed })
    setLocalSettings({ sidebarCollapsed: collapsed })
  },

  setPerformanceDashboardTimeRange: (range) => {
    set({ performanceDashboardTimeRange: range })
    setLocalSettings({ performanceDashboardTimeRange: range })
  },

  loadSettings: (settings) => {
    set({
      sidebarCollapsed: settings.sidebarCollapsed,
      performanceDashboardTimeRange: settings.performanceDashboardTimeRange,
      isLoaded: true,
    })
    // Sync to LocalStorage
    setLocalSettings(settings)
  },

  setIsSyncing: (syncing) => set({ isSyncing: syncing }),
}))
