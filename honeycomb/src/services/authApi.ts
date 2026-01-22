/**
 * Authentication API Service
 */

import { serverClient } from './api'
import type {
  LoginCredentials,
  LoginResponse,
  OrgInfo,
  RegisterCredentials,
  RegisterResponse,
} from '@/types/auth'

/**
 * Authenticates a user with email and password.
 * 
 * @param credentials - User login credentials
 * @returns Promise resolving to login response with token and mustResetPassword
 * @throws {ApiError} When credentials are invalid (401) or other server errors
 * 
 * @example
 * submitLogin({
 *   email: "john.doe@example.com",
 *   password: "StrongPass123",
 *   grantToken: "optional-grant-token"
 * })
 */
export const submitLogin = (credentials: LoginCredentials): Promise<LoginResponse> =>
  serverClient.post<LoginResponse>('/user/login-v2', credentials)

/**
 * Retrieves organization information by its URL path.
 * Used during login to display organization branding and validate org existence.
 * @param orgPath - Organization's URL path identifier (e.g., 'acme-corp')
 * @returns Promise resolving to organization info
 * @throws {ApiError} When organization is not found (404)
 * 
 * @example
 * getOrgInfoByPath('acme-corp')
 */
export const getOrgInfoByPath = (orgPath: string): Promise<{ data: OrgInfo }> =>
  serverClient.get<{ data: OrgInfo }>(`/iam/org/info/${orgPath}`)

/**
 * Registers a new user account.
 * 
 * @param credentials User registration payload
 * @returns {Promise<RegisterResponse>} Registration response
 * @throws {ApiError} When email is already taken (409) or validation fails (400)
 * 
 * @example
 * submitRegister({
 *   email: "john.doe@example.com",
 *   password: "StrongPass123",
 *   firstname: "John",
 *   lastname: "Doe"
 * })
 */
export const submitRegister = (credentials: RegisterCredentials): Promise<RegisterResponse> =>
  serverClient.post<RegisterResponse>('/user/register', credentials)
