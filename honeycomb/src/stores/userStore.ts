import { create } from 'zustand'
import type { User, Organization } from '@/types/user'
import * as userApi from '@/services/userApi'
import * as orgApi from '@/services/orgApi'

export interface UserState {
  user: User | null
  roleId: number | null
  org: Organization | null
  orgLogo: string | null
  isLoading: boolean
  isLoggingOut: boolean

  // Actions
  setUser: (user: User) => void
  setOrg: (org: Organization) => void
  setOrgLogo: (logo: string | null) => void
  initUserProfile: () => Promise<User | null>
  signOut: (redirectUrl?: string) => void

  // Computed-like getters
  fullName: () => string
  isAdmin: () => boolean
}

export const useUserStore = create<UserState>((set, get) => ({
  user: null,
  roleId: null,
  org: null,
  orgLogo: null,
  isLoading: false,
  isLoggingOut: false,

  setUser: (user) => set({ user }),

  setOrg: (org) => {
    set({ org })
    // Update document title to org name
    if (org?.orgName) {
      document.title = org.orgName
    }
  },

  setOrgLogo: (logo) => {
    // Ensure HTTPS
    const secureLogo = logo?.replace('http://', 'https://') || null
    set({ orgLogo: secureLogo })

    // Update favicon if logo exists
    if (secureLogo) {
      let link = document.querySelector('link[data-custom-icon="true"]') as HTMLLinkElement | null
      if (!link) {
        link = document.createElement('link')
        link.setAttribute('data-custom-icon', 'true')
        document.head.appendChild(link)
      }
      link.rel = 'icon'
      link.href = secureLogo
    }
  },

  initUserProfile: async () => {
    set({ isLoading: true })
    try {
      // Fetch user profile - backend returns { data: User }
      const response = await userApi.getUserProfile()
      const user = (response as unknown as { data: User }).data
      set({ user })

      // Fetch current org
      const org = await orgApi.getCurrentTeam()

      set({ roleId: 1, org })

      // Update document title
      if (org?.orgName) {
        document.title = org.orgName
      }

      return user
    } catch (error) {
      console.error('[UserStore] Failed to init user profile:', error)
      return null
    } finally {
      set({ isLoading: false })
    }
  },

  signOut: (redirectUrl) => {
    // Set logging out flag FIRST - prevents flash of error states
    set({ isLoggingOut: true })

    // Clear storage
    localStorage.removeItem('token')
    localStorage.removeItem('context_session_id')
    sessionStorage.clear()

    // Reset store state
    set({
      user: null,
      roleId: null,
      org: null,
      orgLogo: null,
      isLoading: false,
    })

    // Redirect
    window.location.href = redirectUrl || '/login'
  },

  // Computed getters
  fullName: () => {
    const user = get().user
    if (!user) return ''
    return `${user.firstname} ${user.lastname}`.trim()
  },

  isAdmin: () => {
    const user = get().user
    return user?.roles?.includes('admin') ?? false
  },
}))
