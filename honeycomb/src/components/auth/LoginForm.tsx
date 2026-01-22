import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import * as z from 'zod/v3'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useState } from 'react'
import { submitLogin } from '@/services/authApi'
import { useUserStore } from '@/stores/userStore'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'

const loginSchema = z.object({
  email: z.string().email('Please enter a valid email'),
  password: z.string().min(1, 'Please enter your password'),
})

type LoginFormData = z.infer<typeof loginSchema>

interface LoginFormProps {
  orgPath?: string
  orgName?: string
  showSignup?: boolean
}

export function LoginForm({ orgPath, orgName, showSignup = true }: LoginFormProps) {
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const initUserProfile = useUserStore((s) => s.initUserProfile)

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
  })

  const handleRedirect = () => {
    const redirect = searchParams.get('redirect')
    navigate(redirect ? decodeURIComponent(redirect) : '/')
  }

  const handleLogin = async (data: LoginFormData) => {
    setError('')
    setIsSubmitting(true)

    try {
      const res = await submitLogin(data)

      localStorage.removeItem('context_session_id')
      localStorage.setItem('token', `jwt ${res.token}`)

      if (res.mustResetPassword) {
        navigate(`/reset-password?token=${res.token}`)
        return
      }

      await initUserProfile()
      handleRedirect()
    } catch (err: unknown) {
      setError((err as Error)?.message || 'Failed to login. Please check your credentials.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="space-y-4">
      {orgName && (
        <h1 className="text-base font-bold text-center mb-4">
          Welcome to {orgName}'s ARP Platform
        </h1>
      )}

      {error && <p className="text-sm text-destructive text-center">{error}</p>}

      <form onSubmit={handleSubmit(handleLogin)} className="space-y-4">
        <div className="space-y-2">
          <Input
            {...register('email')}
            type="email"
            placeholder="Email"
            disabled={isSubmitting}
          />
          {errors.email && (
            <p className="text-sm text-destructive">{errors.email.message}</p>
          )}
        </div>

        <div className="space-y-2">
          <Input
            {...register('password')}
            type="password"
            placeholder="Password"
            disabled={isSubmitting}
          />
          {errors.password && (
            <p className="text-sm text-destructive">{errors.password.message}</p>
          )}
        </div>

        <Button type="submit" className="w-full h-[42px]" disabled={isSubmitting}>
          {isSubmitting ? 'Logging in...' : 'LOG IN'}
        </Button>
      </form>

      <div className="flex justify-between items-center text-sm">
        <Link to="/forgot-password" className="text-primary hover:underline">
          Forgot password?
        </Link>

        {showSignup && (
          <span className="text-muted-foreground">
            Don't have an account?{' '}
            <Link
              to={orgPath ? `/${orgPath}/register` : '/register'}
              className="text-primary hover:underline"
            >
              Sign up
            </Link>
          </span>
        )}
      </div>
    </div>
  )
}
