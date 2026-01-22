/**
 * Organization API Service
 */

import { serverClient } from './api'
import type {
  Organization,
  OrganizationResponse,
  UpdateOrgLogoPayload,
  UpdateOrgNamePayload,
} from '@/types/user'

/** Organization Management */

/**
 * Retrieves the current team/organization context for the authenticated user.
 * @returns Promise resolving to current team details
 * @throws {ApiError} When not authenticated (401)
 * 
 * @example
 * getCurrentTeam()
 */
export const getCurrentTeam = () =>
  serverClient.get<OrganizationResponse>('/iam/get-current-team')

/**
 * Updates the organization's logo image.
 * @param payload - update payload containing orgId and new logo image (base64 string)
 * @returns Promise resolving to success message
 * @throws {ApiError} When image format is invalid (400) or no admin access (403)
 * 
 * @example
 * setOrganizationLogo({ orgId: 1, orgLogo: 'base64-encoded-image' })
 */
export const setOrganizationLogo = (payload: UpdateOrgLogoPayload) =>
  serverClient.post<{ message: string }>('/iam/set-organization-logo', payload)

/**
 * Renames the organization.
 * @param payload - update payload containing orgId and new name
 * @returns Promise resolving to success message
 * @throws {ApiError} When name is invalid (400) or no admin access (403)
 * 
 * @example
 * updateOrgName({ name: 'New Organization Name', orgId: 1 })
 */
export const updateOrgName = (payload: UpdateOrgNamePayload) =>
  serverClient.post<{ message: string }>('/iam/org/rename', payload)

/**
 * Retrieves all organizations the current user belongs to.
 * Used to populate the organization switcher.
 * @returns Promise resolving to array of organization details including orgName, orgId, teamId, and teamName
 * @throws {ApiError} When not authenticated (401)
 * 
 * @example
 * await getOrganizations()
 */
export const getOrganizations = () =>
  serverClient.get<Organization[]>('/iam/get-user-organizations')

/**
 * Switches the user's current team/organization context.
 * Returns a new auth token scoped to the selected team.
 * @param payload - Object containing the teamId to switch to
 * @returns Promise resolving to new authentication token for the selected team
 * @throws {ApiError} When team not found (404) or no access (403)
 * 
 * @example
 * await setCurrentTeam({ teamId: 1 })
 */
export const setCurrentTeam = (payload: { teamId: number }) =>
  serverClient.post<{ data: { token: string } }>('/iam/set-current-team', payload)
