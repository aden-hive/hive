import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import * as z from 'zod/v3'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useState } from 'react'
import { submitRegister } from '@/services/authApi'
import { useUserStore } from '@/stores/userStore'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import { Eye, EyeOff } from 'lucide-react'

const registerSchema = z
  .object({
    firstname: z.string().min(1, 'First name is required'),
    lastname: z.string().min(1, 'Last name is required'),
    email: z.string().email('Please enter a valid email'),
    password: z.string().min(8, 'Password must be at least 8 characters'),
    confirmPassword: z.string().min(1, 'Please confirm your password'),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: 'Passwords do not match',
    path: ['confirmPassword'],
  })

type RegisterFormData = z.infer<typeof registerSchema>

interface RegisterFormProps {
  orgPath?: string
  orgName?: string
}

export function RegisterForm({ orgPath, orgName }: RegisterFormProps) {
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const initUserProfile = useUserStore((s) => s.initUserProfile)

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isValid },
  } = useForm<RegisterFormData>({
    resolver: zodResolver(registerSchema),
    mode: 'onChange',
  })

  const password = watch('password')
  const confirmPassword = watch('confirmPassword')
  const passwordsMatch = !confirmPassword || password === confirmPassword

  const handleRedirect = () => {
    const redirect = searchParams.get('redirect')
    navigate(redirect ? decodeURIComponent(redirect) : '/')
  }

  const handleRegister = async (data: RegisterFormData) => {
    setError('')
    setIsSubmitting(true)

    try {
      const res = await submitRegister({
        email: data.email,
        password: data.password,
        firstname: data.firstname,
        lastname: data.lastname,
      })

      localStorage.removeItem('context_session_id')
      localStorage.setItem('token', `jwt ${res.token}`)

      await initUserProfile()
      handleRedirect()
    } catch (err: unknown) {
      setError((err as Error)?.message || 'Failed to register. Please try again.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="space-y-4">
      {orgName && (
        <h1 className="text-base font-bold text-center mb-4">
          Join {orgName}'s ARP Platform
        </h1>
      )}

      {!orgName && (
        <h1 className="text-base font-bold text-center mb-4">Create your account</h1>
      )}

      {error && <p className="text-sm text-destructive text-center">{error}</p>}

      <form onSubmit={handleSubmit(handleRegister)} className="space-y-4">
        <div className="flex gap-3">
          <div className="flex-1 space-y-2">
            <Input
              {...register('firstname')}
              type="text"
              placeholder="First name"
              disabled={isSubmitting}
            />
            {errors.firstname && (
              <p className="text-sm text-destructive">{errors.firstname.message}</p>
            )}
          </div>
          <div className="flex-1 space-y-2">
            <Input
              {...register('lastname')}
              type="text"
              placeholder="Last name"
              disabled={isSubmitting}
            />
            {errors.lastname && (
              <p className="text-sm text-destructive">{errors.lastname.message}</p>
            )}
          </div>
        </div>

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
          <div className="relative">
            <Input
              {...register('password')}
              type={showPassword ? 'text' : 'password'}
              placeholder="Password"
              disabled={isSubmitting}
              className="pr-10"
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              tabIndex={-1}
            >
              {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>
          {errors.password && (
            <p className="text-sm text-destructive">{errors.password.message}</p>
          )}
        </div>

        <div className="space-y-2">
          <div className="relative">
            <Input
              {...register('confirmPassword')}
              type={showConfirmPassword ? 'text' : 'password'}
              placeholder="Confirm password"
              disabled={isSubmitting}
              className="pr-10"
            />
            <button
              type="button"
              onClick={() => setShowConfirmPassword(!showConfirmPassword)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              tabIndex={-1}
            >
              {showConfirmPassword ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>
          {errors.confirmPassword && (
            <p className="text-sm text-destructive">{errors.confirmPassword.message}</p>
          )}
          {!errors.confirmPassword && confirmPassword && !passwordsMatch && (
            <p className="text-sm text-destructive">Passwords do not match</p>
          )}
        </div>

        <Button
          type="submit"
          className="w-full h-[42px]"
          disabled={isSubmitting || !isValid || !passwordsMatch}
        >
          {isSubmitting ? 'Creating account...' : 'CREATE ACCOUNT'}
        </Button>
      </form>

      <div className="text-sm text-center">
        <span className="text-muted-foreground">Already have an account? </span>
        <Link
          to={orgPath ? `/${orgPath}/login` : '/login'}
          className="text-primary hover:underline"
        >
          Sign in
        </Link>
      </div>
    </div>
  )
}
