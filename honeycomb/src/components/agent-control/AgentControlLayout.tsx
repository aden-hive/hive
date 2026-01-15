import { useEffect } from 'react'
import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom'
import { useControlSocket } from '@/hooks/useControlSocket'
import { useAgentControlStore } from '@/stores/agentControlStore'
import { useUserStore, type UserState } from '@/stores/userStore'
import { useSidebarCollapsed } from '@/hooks/usePersistedSettings'
import { NotificationBell } from './shared/NotificationBell'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { LiveIndicator } from './shared/LiveIndicator'
import { UserAvatar } from '@/components/user/UserAvatar'
import { Button } from '@/components/ui/button'
import adenLogo from '@/assets/aden-logo.svg'
import adenIcon from '@/assets/aden-icon.png'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import {
  Database,
  BarChart3,
  DollarSign,
  Users,
  PanelLeftClose,
  PanelLeft,
  Settings,
  Sparkles,
  LogOut,
  HelpCircle,
  ExternalLink,
  FileText,
  MessageCircle,
} from 'lucide-react'
import { SettingsModal } from '@/components/settings/SettingsModal'
import { HelpDialog } from './shared/HelpDialog'

const navItems = [
  { value: 'agents', label: 'Agents', path: '/agents', icon: Users },
  { value: 'data', label: 'Logs', path: '/data', icon: Database },
  { value: 'analytics', label: 'Performance Dashboard', path: '/performance-dashboard', icon: BarChart3 },
  { value: 'cost-control', label: 'Cost Control', path: '/cost-control', icon: DollarSign },
]

/**
 * Main layout for Agent Control with sidebar navigation and socket lifecycle.
 */
export function AgentControlLayout() {
  const { connect, disconnect, isConnected } = useControlSocket()
  const hasActiveAgents = useAgentControlStore((state) => state.eventsBuffer.length > 0)
  const user = useUserStore((state: UserState) => state.user)
  const fullName = useUserStore((state: UserState) => state.fullName())
  const signOut = useUserStore((state: UserState) => state.signOut)
  const isLoggingOut = useUserStore((state: UserState) => state.isLoggingOut)
  const navigate = useNavigate()
  const location = useLocation()
  const { sidebarCollapsed, toggleSidebar } = useSidebarCollapsed()

  // Settings modal controlled by URL hash
  const settingsOpen = location.hash === '#settings'
  const handleSettingsClose = (open: boolean) => {
    if (!open) {
      navigate(location.pathname, { replace: true })
    }
  }

  // Help dialog controlled by URL hash
  const helpOpen = location.hash === '#help'
  const handleHelpClose = (open: boolean) => {
    if (!open) {
      navigate(location.pathname, { replace: true })
    }
  }

  // Connect socket on mount
  useEffect(() => {
    connect()
    return () => disconnect()
  }, [connect, disconnect])

  return (
    <div className="h-screen flex bg-background overflow-hidden">
      {/* Sidebar - full height */}
      <aside
        className={cn(
          'h-screen border-r bg-muted/30 flex flex-col transition-all duration-300 overflow-hidden',
          sidebarCollapsed ? 'w-16 cursor-pointer' : 'w-60'
        )}
        onClick={sidebarCollapsed ? toggleSidebar : undefined}
      >
        {/* Sidebar header with title + collapse button */}
        <div
          className={cn(
            'h-14 flex items-center px-3',
            sidebarCollapsed ? 'justify-center' : 'justify-between'
          )}
        >
          {sidebarCollapsed ? (
            <div className="relative group h-10 w-10">
              <img
                src={adenIcon}
                alt="Aden"
                className="h-10 w-10 rounded group-hover:opacity-0 transition-opacity"
              />
              <Button
                variant="ghost"
                size="icon"
                onClick={(e) => {
                  e.stopPropagation()
                  toggleSidebar()
                }}
                aria-label="Expand sidebar"
                className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <PanelLeft />
              </Button>
            </div>
          ) : (
            <>
              <img src={adenLogo} alt="Aden" className="h-6" />
              <Button
                variant="ghost"
                size="icon"
                onClick={toggleSidebar}
                aria-label="Collapse sidebar"
              >
                <PanelLeftClose />
              </Button>
            </>
          )}
        </div>

        {/* Navigation */}
        <TooltipProvider delayDuration={0} key={sidebarCollapsed ? 'collapsed' : 'expanded'}>
          <nav className="flex-1 p-2 space-y-1">
            {navItems.map((item) => (
              <NavLink
                key={item.value}
                to={item.path}
                onClick={(e) => e.stopPropagation()}
                className={({ isActive }) =>
                  cn(
                    'flex items-center w-full px-3 py-2 rounded-lg transition-colors text-sm gap-3',
                    'hover:bg-arp-primary-light',
                    isActive && 'bg-arp-primary-light text-primary font-medium',
                    sidebarCollapsed && 'justify-center px-2'
                  )
                }
              >
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className={cn(
                      "flex items-center",
                      sidebarCollapsed ? "justify-center" : "gap-3 w-full"
                    )}>
                      <item.icon className="h-4 w-4 shrink-0" />
                      <span
                        className={cn(
                          'whitespace-nowrap transition-all duration-300 overflow-hidden',
                          sidebarCollapsed ? 'opacity-0 w-0 ml-0' : 'opacity-100'
                        )}
                      >
                        {item.label}
                      </span>
                    </div>
                  </TooltipTrigger>
                  {sidebarCollapsed && (
                    <TooltipContent side="right" sideOffset={24}>
                      <p>{item.label}</p>
                    </TooltipContent>
                  )}
                </Tooltip>
              </NavLink>
            ))}
          </nav>
        </TooltipProvider>

        {/* User Profile Section - hidden during logout to prevent red avatar flash */}
        {!isLoggingOut && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <div
                className={cn(
                  "mt-auto p-3 cursor-pointer hover:bg-muted/50 transition-colors",
                  !sidebarCollapsed && "border-t"
                )}
                onClick={(e) => e.stopPropagation()}
              >
                <div className={cn(
                  'flex items-center gap-3',
                  sidebarCollapsed && 'justify-center'
                )}>
                  <UserAvatar
                    src={user?.profile_img_url}
                    name={fullName}
                    size="sm"
                  />
                  {!sidebarCollapsed && (
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{fullName}</p>
                      <p className="text-xs text-muted-foreground">Pro</p>
                    </div>
                  )}
                </div>
              </div>
            </DropdownMenuTrigger>
            <DropdownMenuContent side="top" align="start" alignOffset={12} className="w-40">
              <DropdownMenuItem
                onClick={() => navigate(`${location.pathname}#settings`)}
                className="cursor-pointer"
              >
                <Settings className="mr-2 h-4 w-4" />
                Settings
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => console.log('Upgrade clicked')}
                className="cursor-pointer"
              >
                <Sparkles className="mr-2 h-4 w-4" />
                Upgrade
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => signOut()}
                className="cursor-pointer"
              >
                <LogOut className="mr-2 h-4 w-4" />
                Log out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </aside>

      {/* Right side - header bar + content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar with connection status + notifications */}
        <header className="h-14 flex items-center justify-end gap-2 px-4 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
          <LiveIndicator isLive={hasActiveAgents} />

          {/* Connection status - hidden during logout to prevent red flash */}
          {!isLoggingOut && (
            <div
              className={cn(
                'flex items-center gap-1.5 text-xs px-2 py-1 rounded-full',
                isConnected
                  ? 'bg-green-100 text-green-700'
                  : 'bg-red-100 text-red-700'
              )}
            >
              <span
                className={cn(
                  'h-1.5 w-1.5 rounded-full',
                  isConnected ? 'bg-green-500' : 'bg-red-500'
                )}
              />
              {isConnected ? 'Connected' : 'Disconnected'}
            </div>
          )}

          <NotificationBell />

          {/* Help dropdown */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon">
                <HelpCircle className="h-5 w-5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => navigate(`${location.pathname}#help`)}>
                <HelpCircle className="mr-2 h-4 w-4" />
                Guide
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => window.open('https://docs.adenhq.com/', '_blank')}>
                <FileText className="mr-2 h-4 w-4" />
                Documentation
                <ExternalLink className="ml-auto h-3 w-3 opacity-50" />
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => window.open('https://discord.gg/MXE49hrKDk', '_blank')}>
                <MessageCircle className="mr-2 h-4 w-4" />
                Discord
                <ExternalLink className="ml-auto h-3 w-3 opacity-50" />
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </header>

        {/* Content area */}
        <main className="flex-1 flex flex-col overflow-hidden">
          <div className="flex-1 flex flex-col min-h-0 py-6 pl-6">
            <Outlet />
          </div>
        </main>
      </div>

      <SettingsModal open={settingsOpen} onOpenChange={handleSettingsClose} />
      <HelpDialog open={helpOpen} onOpenChange={handleHelpClose} />
    </div>
  )
}
