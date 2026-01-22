/**
 * User API Service
 */

import { serverClient } from './api'
import type {
  UserProfileResponse,
  UpdateProfilePayload,
  UpdateAvatarPayload,
  APITokensResponse,
  APITokenResponse,
  CreateAPITokenPayload,
  TeamRoleResponse,
} from '@/types/user'

/** Default TTL for API tokens: 5 years in seconds (5 * 365 * 24 * 60 * 60). */
const DEFAULT_API_TOKEN_TTL_SECONDS = 157680000

/** Profile Management */

/**
 * Retrieves the current user's profile information.
 * @returns Promise resolving to user profile data including firstname, lastname, email and other user details.
 * @throws {ApiError} When not authenticated (401)
 * 
 * @example
 * getUserProfile()
 */
export const getUserProfile = () =>
  serverClient.get<UserProfileResponse>('/user/profile')

/**
 * Updates the current user's profile information.
 * @param data - Profile fields to update (firstname, lastname, email, etc.)
 * @returns Promise resolving to success message
 * @throws {ApiError} When validation fails (400) or not authenticated (401)
 * 
 * @example
 * updateUserProfile({ firstname: 'John', lastname: 'Doe', email: 'john.doe@example.com' })
 */
export const updateUserProfile = (data: UpdateProfilePayload) =>
  serverClient.put<{ message: string }>('/user/profile', data)

/**
 * Updates the current user's avatar image.
 * @param data - Avatar data including base64-encoded image
 * @returns Promise resolving to the new avatar URL
 * @throws {ApiError} When image format is invalid (400)
 * 
 * @example
 * updateUserAvatar({ userAvatar: 'base64-encoded-image' })
 */
export const updateUserAvatar = (data: UpdateAvatarPayload) =>
  serverClient.post<{ data: string }>('/user/set-user-avatar', data)

/** API Tokens (Developer Tools) */

/**
 * Retrieves all API tokens for the current user.
 * @returns Promise resolving to list of API tokens with metadata
 * @throws {ApiError} When not authenticated (401)
 * 
 * @example
 * getAPITokens()
 */
export const getAPITokens = () =>
  serverClient.get<APITokensResponse>('/user/get-dev-tokens')

/**
 * Creates a new API token for developer tools access.
 * @param label - Display name for the token (e.g., 'Production API Key')
 * @param ttl - Time-to-live in seconds (default: 5 years)
 * @returns Promise resolving to the created token (only shown once)
 * @throws {ApiError} When not authenticated (401)
 * 
 * @example
 * createAPIToken('Production API Key')
 */
export const createAPIToken = (label: string, ttl: number = DEFAULT_API_TOKEN_TTL_SECONDS) =>
  serverClient.post<APITokenResponse>('/user/generate-dev-token', {
    label,
    ttl,
  } as CreateAPITokenPayload)

/** Team/Role */

/**
 * Retrieves the user's role information for a specific team.
 * Used during organization initialization to verify permissions.
 * @param teamId - Team ID to get role for
 * @returns Promise resolving to team role information
 * @throws {ApiError} When team not found (404) or no access (403)
 * 
 * @example
 * getTeamRoleId('123')
 */
export const getTeamRoleId = (teamId: string) =>
  serverClient.get<TeamRoleResponse>(`/iam/team/get-team-role-by-id/${teamId}`)
