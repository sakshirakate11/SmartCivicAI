import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import {
  Activity, ArrowDown, ArrowDownRight, ArrowRight, ArrowUpRight, Bell, Check,
  CheckCircle2, ChevronDown, CircleHelp, Clock3, FileText, Gauge, Globe2,
  ImagePlus, Lightbulb, LocateFixed, LogOut, MapPin, Menu, MessageSquareText,
  Plus, Search, ShieldCheck, Sparkles, Users, X, Zap,
} from 'lucide-react'
import {
  Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import { departments, statusStyle } from './data'
import { compressComplaintImage, getCategoryAdvice } from './complaintStore'
import { api, downloadLegacyBackup, getLegacyBackup } from './api'
import i18n, { tr } from './i18n'

const cx = (...values) => values.filter(Boolean).join(' ')

function LanguageSelector({ variant = 'compact' }) {
  const { i18n: activeI18n } = useTranslation()
  const languages = [
    { code: 'mr', label: 'मराठी' },
    { code: 'en', label: 'English' },
    { code: 'hi', label: 'हिंदी' },
  ]

  if (variant === 'cards') {
    return <section aria-label={tr('Choose your language')} className="mt-7">
      <p className="mb-2 text-xs font-semibold text-slate-600">{tr('Choose your language')}</p>
      <div className="grid max-w-md grid-cols-3 gap-2">
        {languages.map(({ code, label }) => <button
          key={code}
          type="button"
          aria-pressed={(activeI18n.resolvedLanguage || 'en') === code}
          onClick={() => activeI18n.changeLanguage(code)}
          className={cx(
            'rounded-xl border px-3 py-2.5 text-sm font-semibold transition',
            (activeI18n.resolvedLanguage || 'en') === code
              ? 'border-brand bg-blue-50 text-brand'
              : 'border-slate-200 bg-white text-slate-700 hover:border-blue-200',
          )}
        >{label}</button>)}
      </div>
    </section>
  }

  return <label className="inline-flex items-center gap-2 text-xs font-semibold text-slate-600">
    <span className="sr-only">{tr('Select language')}</span>
    <select
      aria-label={tr('Select language')}
      value={activeI18n.resolvedLanguage || 'en'}
      onChange={(event) => activeI18n.changeLanguage(event.target.value)}
      className="max-w-[108px] rounded-lg border border-slate-200 bg-white px-2 py-2 text-xs outline-none focus:border-brand"
    >
      {languages.map(({ code, label }) => <option key={code} value={code}>{label}</option>)}
    </select>
  </label>
}

function localizedNotification(item) {
  const complaintId = item.complaint_id
  const messages = {
    complaint_accepted: 'Complaint {{id}} was accepted by its department.',
    work_started: 'Work has started on complaint {{id}}.',
    work_completed: 'Complaint {{id}} has been completed.',
    eta_updated: 'The estimated completion time for complaint {{id}} was updated.',
    overdue: 'Complaint {{id}} is overdue and needs attention.',
  }
  if (messages[item.kind]) return tr(messages[item.kind], { id: complaintId })

  if (item.kind === 'assigned') {
    const reviewNotice = ' The category suggestion is flagged for municipal review.'
    const hasReviewNotice = item.message.endsWith(reviewNotice)
    const baseMessage = hasReviewNotice ? item.message.slice(0, -reviewNotice.length) : item.message
    const assigned = baseMessage.match(/^Complaint .+ has been assigned to (.+)\.$/)
    if (assigned) {
      const base = tr('Complaint {{id}} has been assigned to {{department}}.', {
        id: complaintId,
        department: assigned[1],
      })
      return hasReviewNotice ? `${base} ${tr(reviewNotice.trim())}` : base
    }
  }

  if (item.kind === 'progress_note_added') {
    const notePrefix = `A progress note was added to complaint ${complaintId}: `
    if (item.message.startsWith(notePrefix)) {
      return `${tr('A progress note was added to complaint {{id}}:', { id: complaintId })} ${item.message.slice(notePrefix.length)}`
    }
  }

  if (item.kind === 'assignment_review_required') {
    const review = item.message.match(/^Complaint .+ needs municipal review: (.*)$/)
    if (review) {
      return `${tr('Complaint {{id}} needs municipal review:', { id: complaintId })} ${review[1]}`
    }
  }

  return item.message
}

function Brand({ light = false }) {
  return <Link to="/" className="inline-flex items-center gap-2.5">
    <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand text-white shadow-lg shadow-blue-200"><Globe2 size={22} strokeWidth={2.1} /></span>
    <span className={cx('font-display text-lg font-extrabold tracking-tight', light ? 'text-white' : 'text-ink')}>{tr("SmartCivic")}<span className="text-brand">{tr("AI")}</span></span>
  </Link>
}

function SampleBadge() {
  return <span className="inline-flex items-center gap-1.5 rounded-full border border-blue-100 bg-blue-50 px-2.5 py-1 text-[11px] font-bold uppercase tracking-[.08em] text-blue-700"><span className="h-1.5 w-1.5 rounded-full bg-blue-500" />{tr("Sample data")}</span>
}

function Header({ dashboard = false, role = 'citizen', user, token, onSignOut }) {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const navigateToSection = (event, sectionId) => {
    event.preventDefault()
    setOpen(false)
    if (location.pathname === '/' && location.hash === `#${sectionId}`) {
      document.getElementById(sectionId)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      return
    }
    navigate({ pathname: '/', hash: `#${sectionId}` })
  }
  const roleLabel = tr({ citizen: 'Citizen account', municipal: 'Municipal officer', department: 'Department officer', admin: 'Administrator' }[role])
  return <header className={cx('relative z-30 border-b border-slate-100 bg-white', dashboard && 'sticky top-0')}>
    <div className="mx-auto flex h-[72px] max-w-[1440px] items-center justify-between px-5 sm:px-8 lg:px-12">
      <Brand />
      <LanguageSelector />
      {dashboard ? <div className="flex items-center gap-3 sm:gap-5">
        <span className="hidden text-sm text-slate-500 sm:block">{tr("Riverdale Municipal Corporation")}</span>
        <NotificationBell token={token} />
        <div className="flex items-center gap-2.5 border-l border-slate-100 pl-3 sm:pl-5">
          <div className="grid h-9 w-9 place-items-center rounded-full bg-blue-100 text-xs font-bold text-blue-700">{(user?.name || 'User').split(/\s+/).map((part) => part[0]).slice(0, 2).join('').toUpperCase()}</div>
          <div className="hidden sm:block"><p className="text-sm font-semibold text-ink">{user?.name || tr('Account')}</p><p className="text-xs text-slate-500">{roleLabel}</p></div>
          <button type="button" onClick={onSignOut} aria-label={tr("Sign out")} className="grid h-9 w-9 place-items-center rounded-lg text-slate-500 hover:bg-slate-50 hover:text-brand"><LogOut size={17} /></button>
        </div>
      </div> : <>
        <nav className="hidden items-center gap-5 lg:flex">
          <a href="/#features" onClick={(event) => navigateToSection(event, 'features')} className="text-sm font-medium text-slate-600 hover:text-brand">{tr("Features")}</a>
          <a href="/#how-it-works" onClick={(event) => navigateToSection(event, 'how-it-works')} className="text-sm font-medium text-slate-600 hover:text-brand">{tr("How it works")}</a>
          <a href="/#impact" onClick={(event) => navigateToSection(event, 'impact')} className="text-sm font-medium text-slate-600 hover:text-brand">{tr("City impact")}</a>
          <Link to="/citizen/login" className="text-sm font-medium text-slate-600 hover:text-brand">{tr("Citizen login")}</Link>
          <Link to="/officer/login" className="text-sm font-medium text-slate-600 hover:text-brand">{tr("Municipal login")}</Link>
          <Link to="/department/login" className="text-sm font-medium text-slate-600 hover:text-brand">{tr("Department login")}</Link>
          <Link to="/admin/login" className="text-sm font-medium text-slate-600 hover:text-brand">{tr("Admin login")}</Link>
          <Link to="/citizen/register" className="rounded-xl bg-brand px-5 py-2.5 text-sm font-semibold text-white shadow-sm shadow-blue-200 transition hover:bg-brand-dark">{tr("Get started")}</Link>
        </nav>
        <button className="grid h-10 w-10 place-items-center rounded-lg text-slate-600 lg:hidden" onClick={() => setOpen(!open)} aria-label={tr("Toggle navigation")}>{open ? <X /> : <Menu />}</button>
        {open && <nav className="absolute left-0 right-0 top-[72px] grid gap-1 border-b border-slate-100 bg-white p-4 shadow-lg lg:hidden">
          <a onClick={(event) => navigateToSection(event, 'features')} href="/#features" className="rounded-lg px-3 py-2.5 text-sm text-slate-700">{tr("Features")}</a>
          <a onClick={(event) => navigateToSection(event, 'how-it-works')} href="/#how-it-works" className="rounded-lg px-3 py-2.5 text-sm text-slate-700">{tr("How it works")}</a>
          <a onClick={(event) => navigateToSection(event, 'impact')} href="/#impact" className="rounded-lg px-3 py-2.5 text-sm text-slate-700">{tr("City impact")}</a>
          <Link to="/citizen/login" className="rounded-lg px-3 py-2.5 text-sm text-slate-700">{tr("Citizen login")}</Link>
          <Link to="/officer/login" className="rounded-lg px-3 py-2.5 text-sm text-slate-700">{tr("Municipal login")}</Link>
          <Link to="/department/login" className="rounded-lg px-3 py-2.5 text-sm text-slate-700">{tr("Department login")}</Link>
          <Link to="/admin/login" className="rounded-lg px-3 py-2.5 text-sm text-slate-700">{tr("Admin login")}</Link>
          <Link to="/citizen/register" className="rounded-lg bg-brand px-3 py-2.5 text-sm font-semibold text-white">{tr("Get started")}</Link>
        </nav>}
      </>}
    </div>
  </header>
}

function NotificationBell({ token }) {
  const [notifications, setNotifications] = useState([])
  const [open, setOpen] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!token) return undefined
    let active = true
    const refresh = async () => {
      try {
        const result = await api.listNotifications(token)
        if (active) {
          setNotifications(result.notifications)
          setError('')
        }
      } catch (requestError) {
        if (active) setError(requestError.message)
      }
    }
    refresh()
    const interval = window.setInterval(refresh, 10000)
    return () => {
      active = false
      window.clearInterval(interval)
    }
  }, [token])
  const unread = notifications.filter((item) => !item.read_at).length
  const markRead = async (item) => {
    if (item.read_at) return
    try {
      await api.markNotificationRead(token, item.id)
      setNotifications((current) => current.map((notice) =>
        notice.id === item.id ? { ...notice, read_at: new Date().toISOString() } : notice
      ))
      setError('')
    } catch (requestError) {
      setError(requestError.message)
    }
  }
  return <div className="relative">
    <button type="button" aria-label={`Notifications${unread ? `, ${unread} unread` : ''}`} onClick={() => setOpen(!open)} className="relative grid h-10 w-10 place-items-center rounded-xl text-slate-500 hover:bg-slate-50"><Bell size={19} />{unread > 0 && <span className="absolute -right-1 -top-1 grid h-5 min-w-5 place-items-center rounded-full bg-rose-500 px-1 text-[10px] font-bold text-white">{unread}</span>}</button>
    {open && <div className="absolute right-0 top-12 z-40 w-[min(360px,calc(100vw-2rem))] rounded-2xl border border-slate-100 bg-white p-3 shadow-xl">
      <div className="flex items-center justify-between px-2 py-1"><h2 className="text-sm font-bold text-ink">{tr("Notifications")}</h2><span className="text-[10px] text-slate-400">{unread} {tr("unread")}</span></div>
      {error && <p role="alert" className="px-2 py-2 text-xs text-rose-700">{tr(error)}</p>}
      <div className="mt-2 max-h-80 space-y-1 overflow-y-auto">{notifications.length ? notifications.map((item) => <button key={item.id} onClick={() => markRead(item)} className={cx('block w-full rounded-xl px-3 py-2.5 text-left hover:bg-slate-50', !item.read_at && 'bg-blue-50/70')}><span className="block text-xs leading-5 text-slate-700">{localizedNotification(item)}</span><span className="mt-1 block text-[10px] text-slate-400">{displayDate(item.created_at)}</span></button>) : !error && <p className="px-3 py-5 text-center text-xs text-slate-400">{tr("No notifications yet.")}</p>}</div>
    </div>}
  </div>
}

function Landing() {
  const location = useLocation()
  useEffect(() => {
    const sectionId = location.hash.slice(1)
    if (!sectionId) return undefined
    const frame = window.requestAnimationFrame(() => {
      document.getElementById(sectionId)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [location.hash])
  return <div className="min-h-screen bg-white">
    <Header />
    <main>
      <section className="grid-paper relative overflow-hidden bg-[#f7faff]">
        <div className="hero-orb pointer-events-none absolute -right-32 -top-32 h-[680px] w-[680px] rounded-full" />
        <div className="relative mx-auto grid max-w-[1240px] items-center gap-12 px-5 pb-20 pt-16 sm:px-8 sm:pt-24 lg:grid-cols-[1fr_.9fr] lg:gap-16 lg:px-12 lg:pb-28">
          <div className="max-w-[620px]">
            <div className="mb-7 inline-flex items-center gap-2 rounded-full border border-blue-100 bg-white px-3.5 py-2 text-xs font-semibold text-blue-700 shadow-sm"><Sparkles size={14} /> {tr("A smarter city starts with you")}</div>
            <h1 className="font-display text-[42px] font-extrabold leading-[1.12] tracking-[-.045em] text-ink sm:text-[56px] lg:text-[64px]">{tr("Your city.")}<br /><span className="text-brand">{tr("Your voice.")}</span><br />{tr("Real change.")}</h1>
            <p className="mt-6 max-w-[500px] text-base leading-7 text-slate-600 sm:text-lg sm:leading-8">{tr("Report civic issues, follow every update, and help your city become a better place to live — one solved problem at a time.")}</p>
            <LanguageSelector variant="cards" />
            <div className="mt-8 flex flex-col gap-3 sm:flex-row">
              <Link to="/citizen/register" className="inline-flex items-center justify-center gap-2 rounded-xl bg-brand px-6 py-3.5 text-sm font-bold text-white shadow-lg shadow-blue-200 transition hover:-translate-y-0.5 hover:bg-brand-dark">{tr("Report an issue")} <ArrowRight size={17} /></Link>
              <Link to="/citizen/login" className="inline-flex items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-6 py-3.5 text-sm font-bold text-ink transition hover:border-blue-200 hover:text-brand">{tr("Track a complaint")} <ArrowDownRight size={17} /></Link>
            </div>
            <div className="mt-9 flex items-center gap-4 border-t border-slate-200/80 pt-6">
              <div className="flex -space-x-2">{['A', 'R', 'M', 'S'].map((letter, i) => <div key={letter} className={cx('grid h-8 w-8 place-items-center rounded-full border-2 border-[#f7faff] text-[10px] font-bold text-white', ['bg-violet-500', 'bg-emerald-500', 'bg-orange-400', 'bg-blue-500'][i])}>{letter}</div>)}</div>
              <p className="text-xs text-slate-500"><strong className="text-slate-700">{tr("2,400+ citizens")}</strong> {tr("building a better Riverdale")}</p>
            </div>
          </div>
          <div className="relative mx-auto w-full max-w-[520px] lg:ml-auto">
            <div className="absolute -right-5 top-10 h-48 w-48 rounded-full bg-blue-100/70 blur-3xl" />
            <div className="relative rounded-[28px] border border-white bg-white p-3 shadow-[0_25px_80px_rgba(32,68,130,.15)] sm:p-4">
              <div className="overflow-hidden rounded-[20px] bg-[#eaf2fb]">
                <div className="flex items-center justify-between bg-white px-5 py-4"><div><p className="text-xs font-semibold text-slate-400">{tr("RIVERDALE CITY")}</p><p className="font-display text-sm font-bold text-ink">{tr("Community overview")}</p></div><span className="flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-[10px] font-bold text-emerald-700"><span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />{tr("Live pulse")}</span></div>
                <div className="relative h-[290px] overflow-hidden sm:h-[330px]" style={{ backgroundImage: 'linear-gradient(0deg, rgba(219,233,248,.93), rgba(239,247,255,.42)), url("https://images.unsplash.com/photo-1519501025264-65ba15a82390?auto=format&fit=crop&w=1000&q=85")', backgroundSize: 'cover', backgroundPosition: 'center' }}>
                  <svg className="absolute inset-0 h-full w-full opacity-70" viewBox="0 0 500 330" fill="none" aria-hidden="true"><path d="M10 40 100 76 180 58 245 110 310 70 415 90 500 35M-10 160l100-30 90 42 85-18 95 48 140-55M15 300l65-60 105 20 90-60 105 30 130-60" stroke="#fff" strokeWidth="16"/><path d="M40 0 60 100 28 185l55 100-10 45M155-5l-10 75 48 90-30 100 30 70M285 0l-35 100 40 70-26 85 25 75M425-5l-40 110 48 82-38 80 32 70" stroke="#fff" strokeWidth="13"/></svg>
                  <div className="absolute left-[25%] top-[27%] grid h-10 w-10 place-items-center rounded-full border-[5px] border-white bg-rose-500 text-white shadow-lg"><MapPin size={17} fill="white" /></div>
                  <div className="absolute left-[60%] top-[22%] grid h-10 w-10 place-items-center rounded-full border-[5px] border-white bg-amber-400 text-white shadow-lg"><Zap size={16} fill="white" /></div>
                  <div className="absolute left-[50%] top-[58%] grid h-10 w-10 place-items-center rounded-full border-[5px] border-white bg-emerald-500 text-white shadow-lg"><Check size={17} /></div>
                  <div className="absolute bottom-4 left-4 right-4 rounded-2xl border border-white/80 bg-white/95 p-4 shadow-lg backdrop-blur sm:bottom-5 sm:left-5 sm:right-auto sm:w-[245px]">
                    <div className="mb-3 flex items-center justify-between"><span className="text-xs font-bold text-ink">{tr("City at a glance")}</span><span className="text-[10px] font-medium text-slate-400">{tr("THIS MONTH")}</span></div>
                    <div className="grid grid-cols-3 gap-2"><MiniStat value="1,284" label="Reported" /><MiniStat value="86%" label="Resolved" green /><MiniStat value="2.4d" label="Avg. time" /></div>
                  </div>
                </div>
              </div>
            </div>
            <div className="absolute -left-7 top-[30%] hidden items-center gap-3 rounded-2xl border border-slate-100 bg-white px-4 py-3 shadow-card sm:flex"><span className="grid h-9 w-9 place-items-center rounded-xl bg-emerald-50 text-emerald-600"><CheckCircle2 size={18} /></span><div><p className="text-xs font-bold text-ink">{tr("Issue resolved!")}</p><p className="text-[10px] text-slate-500">{tr("Pothole · Ward 04")}</p></div></div>
          </div>
        </div>
      </section>
      <section id="impact" className="mx-auto max-w-[1240px] px-5 py-14 sm:px-8 lg:px-12 lg:py-16">
        <div className="grid grid-cols-2 gap-6 rounded-3xl border border-slate-100 bg-white p-6 shadow-card sm:grid-cols-4 sm:p-9">
          <Impact value="12.8k+" label="Issues reported" />
          <Impact value="10.4k" label="Issues resolved" />
          <Impact value="86%" label="Resolution rate" />
          <Impact value="2.4 days" label="Average response" />
        </div>
      </section>
      <section id="features" className="mx-auto max-w-[1240px] px-5 pb-16 sm:px-8 lg:px-12 lg:pb-20">
        <div className="mb-8 max-w-xl"><p className="text-xs font-bold uppercase tracking-[.16em] text-brand">{tr("Built for civic action")}</p><h2 className="mt-3 font-display text-3xl font-extrabold tracking-tight text-ink sm:text-4xl">{tr("Everything in one clear place")}</h2><p className="mt-3 text-sm leading-6 text-slate-500 sm:text-base">{tr("A shared view that helps residents report confidently and helps city teams respond with clarity.")}</p></div>
        <div className="grid gap-4 md:grid-cols-3">
          <Step number="01" icon={<MapPin size={21} />} title={tr("Reports with context")} body="Add a category, clear description, photo evidence, and GPS or a manual location to help the right team find the issue." />
          <Step number="02" icon={<Activity size={21} />} title={tr("Transparent tracking")} body="Follow each complaint ID from submission through department assignment, work in progress, and resolution." />
          <Step number="03" icon={<ShieldCheck size={21} />} title={tr("Coordinated city teams")} body="Municipal and admin views bring queues, sample insights, department workloads, and progress into one workspace." />
        </div>
      </section>
      <section id="how-it-works" className="bg-[#f7faff] px-5 py-16 sm:px-8 lg:px-12 lg:py-20">
        <div className="mx-auto max-w-[1240px]">
          <div className="mx-auto max-w-xl text-center"><p className="text-xs font-bold uppercase tracking-[.16em] text-brand">{tr("Simple by design")}</p><h2 className="mt-3 font-display text-3xl font-extrabold tracking-tight text-ink sm:text-4xl">{tr("From report to resolution")}</h2><p className="mt-3 text-sm leading-6 text-slate-500 sm:text-base">{tr("A transparent process that puts people first and keeps progress moving.")}</p></div>
          <div className="mt-10 grid gap-4 md:grid-cols-3">
            <Step number="01" icon={<MessageSquareText size={21} />} title={tr("Tell us what's wrong")} body="Share the issue, add a photo, and pinpoint the location. It takes less than a minute." />
            <Step number="02" icon={<Activity size={21} />} title={tr("Follow the progress")} body="Your report reaches the right team. Get clear status updates at every step." />
            <Step number="03" icon={<CheckCircle2 size={21} />} title={tr("See your city improve")} body="Confirm the fix, share feedback, and see the collective impact in your neighborhood." />
          </div>
          <div className="mt-9 text-center"><SampleBadge /><p className="mt-2 text-xs text-slate-400">{tr("Dashboard figures shown are illustrative sample data.")}</p></div>
        </div>
      </section>
    </main>
    <footer className="border-t border-slate-100 bg-white px-5 py-7 sm:px-8"><div className="mx-auto flex max-w-[1240px] flex-col items-center justify-between gap-3 sm:flex-row"><Brand /><p className="text-xs text-slate-400">{tr("© 2025 SmartCivicAI · A better city, together.")}</p><div className="flex gap-4 text-xs text-slate-500"><Link to="/officer/login" className="hover:text-brand">{tr("Officer portal")}</Link><Link to="/admin/login" className="hover:text-brand">{tr("Admin portal")}</Link></div></div></footer>
  </div>
}

function MiniStat({ value, label, green }) { return <div><p className={cx('font-display text-base font-extrabold', green ? 'text-emerald-600' : 'text-ink')}>{value}</p><p className="mt-0.5 text-[9px] text-slate-400">{tr(label)}</p></div> }
function Impact({ value, label }) { return <div className="text-center"><p className="font-display text-2xl font-extrabold tracking-tight text-ink sm:text-3xl">{value}</p><p className="mt-1 text-xs text-slate-500 sm:text-sm">{tr(label)}</p></div> }
function Step({ number, icon, title, body }) { return <div className="rounded-2xl border border-slate-100 bg-white p-6 shadow-sm sm:p-7"><div className="flex items-center justify-between"><span className="grid h-11 w-11 place-items-center rounded-xl bg-blue-50 text-brand">{icon}</span><span className="font-display text-xs font-bold tracking-widest text-slate-300">{number}</span></div><h3 className="mt-5 font-display text-lg font-bold text-ink">{tr(title)}</h3><p className="mt-2 text-sm leading-6 text-slate-500">{tr(body)}</p></div> }

function AuthPage({ type, onAuthenticated }) {
  const navigate = useNavigate()
  const titles = { login: ['Welcome back', 'Sign in to stay connected to your city.'], register: ['Join your community', 'Create an account and help make a difference.'], officer: ['Officer sign in', 'Access your municipal operations workspace.'], department: ['Department sign in', 'Access the complaint queue assigned to your department.'], admin: ['Administrator sign in', 'Manage city services from one place.'] }
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const isRegister = type === 'register'
  const expectedRole = type === 'officer' ? 'municipal' : type === 'department' ? 'department' : type === 'admin' ? 'admin' : 'citizen'
  const submit = async (event) => {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      const form = new FormData(event.currentTarget)
      const credentials = {
        email: form.get('email'),
        password: form.get('password'),
      }
      const result = isRegister
        ? await api.register({
          ...credentials,
          name: form.get('name'),
          phone: form.get('phone'),
          sms_consent: form.get('sms_consent') === 'on',
        })
        : await api.login(credentials)
      const expectedRoles = type === 'officer' ? ['municipal', 'department'] : [expectedRole]
      if (!expectedRoles.includes(result.user.role)) {
        throw new Error(tr('This account is registered as {{role}}. Use the matching sign-in page.', { role: tr(result.user.role) }))
      }
      onAuthenticated(result)
      navigate({ citizen: '/citizen', municipal: '/municipal', department: '/department', admin: '/admin' }[result.user.role])
    } catch (authError) {
      setError(authError.message)
    } finally {
      setSubmitting(false)
    }
  }
  return <div className="min-h-screen bg-[#f5f8fc]">
    <Header />
    <main className="grid min-h-[calc(100vh-73px)] lg:grid-cols-[1fr_.85fr]">
      <div className="flex items-center justify-center px-5 py-12 sm:px-10">
        <div className="w-full max-w-[430px]">
          <Link to="/" className="mb-8 inline-flex items-center gap-1 text-xs font-semibold text-slate-500 hover:text-brand"><ArrowDown className="rotate-90" size={14} /> {tr("Back to home")}</Link>
          <div className="mb-7"><h1 className="font-display text-3xl font-extrabold tracking-tight text-ink">{tr(titles[type][0])}</h1><p className="mt-2 text-sm text-slate-500">{tr(titles[type][1])}</p></div>
          <form className="space-y-4" onSubmit={submit}>
            {isRegister && <div><label className="mb-1.5 block text-xs font-semibold text-slate-700">{tr("Full name")}</label><input name="name" required maxLength="120" placeholder={tr("e.g. Alex Smith")} className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none transition placeholder:text-slate-400 focus:border-brand focus:ring-4 focus:ring-blue-50" /></div>}
            <div><label className="mb-1.5 block text-xs font-semibold text-slate-700">{tr("Email address")}</label><input name="email" type="email" required maxLength="254" placeholder={tr("you@example.com")} className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none transition placeholder:text-slate-400 focus:border-brand focus:ring-4 focus:ring-blue-50" /></div>
            {isRegister && <div><label className="mb-1.5 block text-xs font-semibold text-slate-700">{tr("Phone number")} <span className="font-normal text-slate-400">{tr("(optional)")}</span></label><input name="phone" type="tel" maxLength="40" placeholder="+91 98765 43210" className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none transition placeholder:text-slate-400 focus:border-brand focus:ring-4 focus:ring-blue-50" /></div>}
            {isRegister && <label className="flex items-start gap-2 text-xs leading-5 text-slate-600"><input name="sms_consent" type="checkbox" className="mt-1 accent-brand" />{tr("I agree to receive complaint status SMS updates on the phone number above. This is optional and can be withdrawn later.")}</label>}
            <div><div className="mb-1.5 flex justify-between"><label className="text-xs font-semibold text-slate-700">{tr("Password")}</label>{!isRegister && <span className="text-xs text-slate-400">{tr("Contact your administrator to reset it")}</span>}</div><input name="password" type="password" required minLength="10" maxLength="128" autoComplete={isRegister ? 'new-password' : 'current-password'} placeholder={tr(isRegister ? 'At least 10 characters' : 'Enter your password')} className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none transition placeholder:text-slate-400 focus:border-brand focus:ring-4 focus:ring-blue-50" /></div>
            {error && <p role="alert" className="text-sm text-rose-600">{tr(error)}</p>}
            <button disabled={submitting} type="submit" className="flex w-full items-center justify-center gap-2 rounded-xl bg-brand px-4 py-3.5 text-sm font-bold text-white shadow-md shadow-blue-100 transition hover:bg-brand-dark disabled:opacity-60">{tr(submitting ? 'Please wait…' : isRegister ? 'Create account' : 'Sign in')} <ArrowRight size={16} /></button>
          </form>
          <p className="mt-5 text-center text-xs text-slate-500">{tr(isRegister ? 'Already have an account?' : "New to SmartCivicAI?")} <Link className="font-bold text-brand hover:text-brand-dark" to={isRegister ? '/citizen/login' : '/citizen/register'}>{tr(isRegister ? 'Sign in' : 'Create an account')}</Link></p>
          <p className="mt-6 text-center text-[11px] leading-5 text-slate-400">{tr("Credentials are verified by the Flask API. Municipal and admin accounts must be provisioned by an administrator.")}</p>
        </div>
      </div>
      <div className="relative hidden overflow-hidden bg-[#123d8a] p-12 lg:flex lg:items-end">
        <div className="absolute inset-0 opacity-30" style={{ backgroundImage: 'url("https://images.unsplash.com/photo-1519501025264-65ba15a82390?auto=format&fit=crop&w=1200&q=85")', backgroundSize: 'cover', backgroundPosition: 'center' }} />
        <div className="absolute inset-0 bg-gradient-to-t from-[#0c2860] via-[#123d8a]/65 to-[#123d8a]/35" />
        <div className="relative max-w-lg pb-5 text-white"><span className="mb-5 grid h-12 w-12 place-items-center rounded-2xl bg-white/15"><Globe2 size={24} /></span><h2 className="font-display text-4xl font-extrabold leading-tight">{tr("Small actions.")}<br />{tr("Big city impact.")}</h2><p className="mt-4 max-w-md text-sm leading-6 text-blue-100">{tr("Together, citizens and city teams are building a more responsive, more livable Riverdale.")}</p><div className="mt-9 flex items-center gap-6 border-t border-white/15 pt-6"><MiniStat value="10.4k" label="Issues resolved" /><MiniStat value="86%" label="Resolution rate" green /></div></div>
      </div>
    </main>
  </div>
}

const roleNavigation = {
  citizen: [{ label: 'Overview', icon: Gauge, to: '/citizen' }, { label: 'My complaints', icon: FileText, to: '/citizen/complaints' }, { label: 'Report an issue', icon: Plus, to: '/citizen/report' }],
  municipal: [{ label: 'Overview', icon: Gauge, to: '/municipal' }, { label: 'Complaints', icon: FileText, to: '/municipal/complaints' }, { label: 'Departments', icon: Users, to: '/municipal/departments' }],
  department: [{ label: 'Department dashboard', icon: Gauge, to: '/department' }],
  admin: [{ label: 'Overview', icon: Gauge, to: '/admin' }, { label: 'All complaints', icon: FileText, to: '/admin/complaints' }, { label: 'Citizens', icon: Users, to: '/admin/citizens' }],
}

function AppShell({ role, children, apiError, loading, user, token, onSignOut }) {
  const [mobileOpen, setMobileOpen] = useState(false)
  const currentNav = roleNavigation[role]
  const roleName = tr({ citizen: 'Citizen portal', municipal: 'Municipal portal', department: 'Department portal', admin: 'Admin portal' }[role])
  return <div className="min-h-screen bg-canvas">
    <Header dashboard role={role} user={user} token={token} onSignOut={onSignOut} />
    <div className="mx-auto flex max-w-[1600px]">
      <aside className={cx('fixed inset-y-[72px] left-0 z-20 w-[252px] border-r border-slate-100 bg-white px-4 py-6 transition-transform lg:sticky lg:top-[72px] lg:block lg:h-[calc(100vh-72px)] lg:translate-x-0', mobileOpen ? 'translate-x-0' : '-translate-x-full')}>
        <div className="mb-6 px-3"><p className="text-[10px] font-bold uppercase tracking-[.16em] text-slate-400">{roleName}</p><p className="mt-1 text-sm font-semibold text-ink">{tr(role === 'department' ? user?.department : 'Riverdale · Ward 04')}</p></div>
        <nav className="space-y-1">{currentNav.map(({ label, icon: Icon, to }) => <NavLink key={to} to={to} end={to.split('/').length === 2} onClick={() => setMobileOpen(false)} className={({ isActive }) => cx('flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition', isActive ? 'bg-blue-50 text-brand' : 'text-slate-600 hover:bg-slate-50')}><Icon size={18} />{tr(label)}</NavLink>)}</nav>
        <div className="mt-8 border-t border-slate-100 pt-5"><p className="mb-2 px-3 text-[10px] font-bold uppercase tracking-[.16em] text-slate-400">{tr("Resources")}</p><a href="#support" className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-slate-600 hover:bg-slate-50"><CircleHelp size={18} />{tr("Help & support")}</a>{role === 'citizen' && <Link to="/officer/login" className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-slate-600 hover:bg-slate-50"><ShieldCheck size={18} />{tr("Municipal officer login")}</Link>}</div>
        <div className="absolute bottom-5 left-4 right-4 rounded-2xl bg-[#f5f8fc] p-4"><div className="flex items-center gap-2 text-xs font-bold text-ink"><ShieldCheck size={16} className="text-blue-600" /> {tr("Flask + SQLite API")}</div><p className="mt-2 text-[11px] leading-4 text-slate-500">{tr("Complaints are stored by the backend, with access checked by account role.")}</p></div>
      </aside>
      {mobileOpen && <button aria-label={tr("Close navigation")} onClick={() => setMobileOpen(false)} className="fixed inset-0 z-10 bg-ink/30 lg:hidden" />}
      <main className="min-w-0 flex-1 px-4 pb-12 pt-6 sm:px-7 lg:px-10 lg:pt-9">
        <button onClick={() => setMobileOpen(true)} className="mb-4 inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 lg:hidden"><Menu size={16} /> {tr("Menu")}</button>
        <div className="mx-auto max-w-[1240px]">
          {apiError && <div role="alert" className="mb-5 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs leading-5 text-rose-800">{tr(apiError)}</div>}
          {loading && <div role="status" className="mb-5 rounded-xl border border-blue-100 bg-blue-50 px-4 py-3 text-xs text-blue-800">{tr("Loading current records…")}</div>}
          {children}
        </div>
      </main>
    </div>
  </div>
}

function PageHeading({ eyebrow, title, description, action }) {
  return <div className="mb-7 flex flex-col justify-between gap-4 sm:flex-row sm:items-end"><div><p className="mb-2 text-[11px] font-bold uppercase tracking-[.15em] text-brand">{tr(eyebrow)}</p><h1 className="font-display text-2xl font-extrabold tracking-tight text-ink sm:text-[30px]">{tr(title)}</h1><p className="mt-1.5 text-sm text-slate-500">{tr(description)}</p></div>{action}</div>
}

function StatCard({ icon: Icon, label, value, delta, tint = 'blue', footnote }) {
  const colors = { blue: 'bg-blue-50 text-brand', amber: 'bg-amber-50 text-amber-600', violet: 'bg-violet-50 text-violet-600', green: 'bg-emerald-50 text-emerald-600', rose: 'bg-rose-50 text-rose-600' }
  return <div className="rounded-2xl border border-slate-100 bg-white p-5 shadow-card sm:p-5"><div className="flex items-start justify-between"><span className={cx('grid h-10 w-10 place-items-center rounded-xl', colors[tint])}><Icon size={19} /></span>{delta && <span className="flex items-center gap-1 text-[11px] font-bold text-emerald-600"><ArrowUpRight size={14} />{delta}</span>}</div><p className="mt-4 font-display text-[27px] font-extrabold tracking-tight text-ink">{value}</p><p className="mt-0.5 text-xs font-medium text-slate-500">{tr(label)}</p>{footnote && <p className="mt-2 text-[10px] text-slate-400">{tr(footnote)}</p>}</div>
}

function Panel({ title, subtitle, action, children, className }) {
  return <section className={cx('rounded-2xl border border-slate-100 bg-white p-5 shadow-card sm:p-6', className)}><div className="mb-5 flex items-start justify-between gap-3"><div><h2 className="font-display text-sm font-bold text-ink">{tr(title)}</h2>{subtitle && <p className="mt-1 text-xs text-slate-400">{tr(subtitle)}</p>}</div>{action}</div>{children}</section>
}

function ComplaintImage({ complaint, token }) {
  const [imageUrl, setImageUrl] = useState('')
  const [error, setError] = useState(false)
  useEffect(() => {
    if (!complaint.image_url || !token) return undefined
    const controller = new AbortController()
    let objectUrl = ''
    fetch(api.imageUrl(complaint.image_url), {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
    }).then((response) => {
      if (!response.ok) throw new Error(`Image request failed (${response.status}).`)
      return response.blob()
    }).then((blob) => {
      objectUrl = URL.createObjectURL(blob)
      setImageUrl(objectUrl)
    }).catch((loadError) => {
      if (loadError.name !== 'AbortError') setError(true)
    })
    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [complaint.image_url, token])
  if (!complaint.image_url) return <span className="text-[10px] text-slate-400">{tr("No photo")}</span>
  if (error) return <span className="text-[10px] text-rose-500">{tr("Image unavailable")}</span>
  if (!imageUrl) return <span className="text-[10px] text-slate-400">{tr("Loading photo…")}</span>
  return <a href={imageUrl} target="_blank" rel="noreferrer" aria-label={`Open photo for ${complaint.id}`}><img src={imageUrl} alt={`Evidence for ${complaint.title}`} className="h-10 w-12 rounded-lg object-cover" /></a>
}

function displayDate(value) {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime())
    ? value
    : new Intl.DateTimeFormat(i18n.resolvedLanguage, { dateStyle: 'medium', timeStyle: 'short' }).format(parsed)
}

function toLocalDateTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset())
  return date.toISOString().slice(0, 16)
}

function ComplaintInsights({ complaint, token }) {
  const [open, setOpen] = useState(false)
  const [details, setDetails] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const toggle = async () => {
    if (open) {
      setOpen(false)
      return
    }
    setOpen(true)
    if (details) return
    setLoading(true)
    setError('')
    try {
      setDetails(await api.getComplaintInsights(token, complaint.id))
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }
  return <div className="mt-2">
    <button type="button" onClick={toggle} className="text-[10px] font-semibold text-brand hover:text-brand-dark">{tr(open ? 'Hide analysis' : 'View AI / ETA analysis')}</button>
    {open && <div className="mt-1 rounded-lg bg-slate-50 p-2 text-[10px] leading-4 text-slate-600">
      {loading && <p>{tr("Loading analysis…")}</p>}
      {error && <p role="alert" className="text-rose-600">{tr(error)}</p>}
      {details && <>
        <p>{tr("ML prediction:")} {details.classifier.category ? tr(details.classifier.category) : tr('Unavailable')}{details.classifier.confidence != null && ` · ${Math.round(details.classifier.confidence * 100)}${tr('% confidence')}`}</p>
        {details.classifier.requires_review && <p className="font-bold text-amber-700">{tr("Needs Review")}</p>}
        <p>{tr("Citizen-selected category:")} {details.selected_category}</p>
        <p>{tr("Actual assigned department:")} {details.assigned_department}</p>
        {details.review_reason && <p>{details.review_reason}</p>}
        <p>{tr("Priority suggestion:")} {tr(details.priority.predicted || 'Unavailable')} {tr("· Urgency indicator")} {details.urgency.score ?? '—'} {tr("· Sentiment indicator")} {tr(details.urgency.sentiment_label)}</p>
        <p>{tr("ETA:")} {details.eta.expected_completion_at ? displayDate(details.eta.expected_completion_at) : tr('Not available')} · {tr(details.eta.method || 'No method recorded')} {tr("(estimate, not guarantee)")}</p>
        {details.accepted_at && <p>{tr("Accepted by the assigned department at")} {displayDate(details.accepted_at)}.</p>}
        {details.classifier.requires_review && <p className="text-slate-500">{tr("The ML recommendation needs review. The verified category mapping remains the routing authority.")}</p>}
        <p className="mt-1 font-semibold">{tr("Similar reports")}</p>
        {details.duplicates.length ? details.duplicates.map((item) => <p key={item.id}>{item.id} · {tr(item.category)} · {tr(item.status)} · {Math.round(item.similarity * 100)}{tr("% text similarity")}</p>) : <p>{tr("No similar reports identified.")}</p>}
      </>}
    </div>}
  </div>
}

function FeedbackControl({ complaint, token }) {
  const [rating, setRating] = useState('5')
  const [comment, setComment] = useState('')
  const [saved, setSaved] = useState(Boolean(complaint.feedback_rating))
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  if (!['Completed', 'Resolved'].includes(complaint.status)) return null
  if (saved) return <p className="mt-2 text-[10px] text-emerald-700">{tr("Thank you for rating this service")}{complaint.feedback_rating ? ` · ${complaint.feedback_rating}/5` : ''}.</p>
  const submit = async () => {
    setSaving(true)
    setError('')
    try {
      await api.submitFeedback(token, complaint.id, { rating: Number(rating), comment })
      setSaved(true)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setSaving(false)
    }
  }
  return <div className="mt-2 space-y-1">
    <div className="flex items-center gap-1">
      <select aria-label={`Rate ${complaint.id}`} value={rating} onChange={(event) => setRating(event.target.value)} className="rounded border border-slate-200 bg-white px-1 py-1 text-[10px]">{[5, 4, 3, 2, 1].map((value) => <option key={value} value={value}>{value}/5</option>)}</select>
      <input aria-label={`Feedback for ${complaint.id}`} value={comment} onChange={(event) => setComment(event.target.value)} maxLength={1000} placeholder={tr("Optional feedback")} className="min-w-0 flex-1 rounded border border-slate-200 px-2 py-1 text-[10px]" />
      <button type="button" disabled={saving} onClick={submit} className="rounded bg-brand px-2 py-1 text-[10px] font-semibold text-white disabled:opacity-50">{tr(saving ? 'Saving' : 'Rate')}</button>
    </div>
    {error && <p role="alert" className="text-[10px] text-rose-600">{tr(error)}</p>}
  </div>
}

function ComplaintTable({ complaints, token, showCitizen = false, onAssign, onPriorityChange, compact = false, allowFeedback = false }) {
  return <div className="scrollbar-hidden -mx-5 overflow-x-auto sm:mx-0">
    <table className={cx('w-full min-w-[980px] text-left', compact && 'min-w-[760px]')}>
      <thead><tr className="border-y border-slate-100 bg-slate-50/70 text-[10px] font-bold uppercase tracking-[.1em] text-slate-400">
        <th className="px-5 py-3 sm:px-4">{tr("Complaint")}</th><th className="px-4 py-3">{tr("Photo")}</th>
        {showCitizen && <th className="px-4 py-3">{tr("Citizen")}</th>}<th className="px-4 py-3">{tr("Category & description")}</th>
        <th className="px-4 py-3">{tr("Location")}</th><th className="px-4 py-3">{tr("Status")}</th>
        <th className="px-4 py-3">{tr("Department & latest update")}</th>{onPriorityChange && <th className="px-4 py-3">{tr("Priority")}</th>}<th className="px-4 py-3">{tr("ETA")}</th><th className="px-4 py-3">{tr("Submitted")}</th>
      </tr></thead>
      <tbody>{complaints.map((item) => <tr key={item.id} className="border-b border-slate-50 last:border-0 hover:bg-slate-50/60">
        <td className="px-5 py-3.5 sm:px-4"><p className="whitespace-nowrap text-xs font-semibold text-ink">{item.title}</p><p className="mt-1 text-[10px] text-slate-400">{item.id}</p></td>
        <td className="px-4 py-3.5"><ComplaintImage complaint={item} token={token} /></td>
        {showCitizen && <td className="px-4 py-3.5 text-xs text-slate-600">{item.citizen || tr('Citizen details unavailable')}</td>}
        <td className="max-w-[240px] px-4 py-3.5"><p className="text-xs font-medium text-slate-700">{tr(item.category)}</p><p className="mt-1 line-clamp-2 text-[10px] leading-4 text-slate-400" title={item.description}>{item.description || tr('No additional description provided.')}</p><p className="mt-1 text-[10px] text-slate-500">{tr("ML suggestion:")} {item.predicted_category ? tr(item.predicted_category) : tr('Unavailable')}{item.category_confidence != null ? ` · ${Math.round(item.category_confidence * 100)}%` : ` · ${tr('no confidence score')}`}{item.prediction_needs_review && <span className="ml-1 font-bold text-amber-700">{tr("· Needs Review")}</span>}</p><ComplaintInsights complaint={item} token={token} />{allowFeedback && <FeedbackControl complaint={item} token={token} />}</td>
        <td className="max-w-[180px] px-4 py-3.5 text-xs text-slate-500">{item.location}</td>
        <td className="px-4 py-3.5"><span className={cx('whitespace-nowrap rounded-full px-2.5 py-1 text-[10px] font-bold ring-1 ring-inset', statusStyle[item.status] || statusStyle.Pending)}>{tr(item.status)}</span></td>
        <td className="px-4 py-3.5">{onAssign ? <select aria-label={`Assign ${item.id}`} value={item.department} onChange={(event) => onAssign(item.id, event.target.value)} className="max-w-[150px] rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[10px] text-slate-600 outline-none focus:border-brand">{item.assignment_review_required && <option value={item.department} disabled>{tr("Needs municipal review")}</option>}{departments.map((department) => <option key={department} value={department}>{tr(department)}</option>)}</select> : <><p className={cx('text-[11px] font-medium', item.assignment_review_required ? 'text-amber-700' : 'text-slate-600')}>{item.assignment_review_required ? tr('Needs municipal review') : tr(item.department || 'Unassigned')}</p>{item.latest_progress_note && <p className="mt-1 max-w-[190px] line-clamp-2 text-[10px] text-slate-400" title={item.latest_progress_note}>{item.latest_progress_note}</p>}</>}</td>
        {onPriorityChange && <td className="px-4 py-3.5"><select aria-label={`Set priority for ${item.id}`} value={item.priority || 'Medium'} onChange={(event) => onPriorityChange(item.id, event.target.value)} className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[10px] text-slate-600 outline-none focus:border-brand">{['Low', 'Medium', 'High'].map((priority) => <option key={priority} value={priority}>{tr(priority)}</option>)}</select></td>}
        <td className="whitespace-nowrap px-4 py-3.5 text-[10px] text-slate-500">{item.expected_completion_at ? displayDate(item.expected_completion_at) : '—'}</td>
        <td className="whitespace-nowrap px-4 py-3.5 text-[11px] text-slate-400">{displayDate(item.created_at || item.date)}</td>
      </tr>)}</tbody>
    </table>
  </div>
}

function CitizenDashboard({ complaints, addComplaint, token, summary, loading, user, onImportLegacy }) {
  const navigate = useNavigate()
  return <Routes>
    <Route index element={<CitizenOverview complaints={complaints} token={token} summary={summary} loading={loading} user={user} />} />
    <Route path="complaints" element={<CitizenHistory complaints={complaints} token={token} loading={loading} onImportLegacy={onImportLegacy} />} />
    <Route path="report" element={<ReportForm addComplaint={addComplaint} onDone={(id) => navigate('/citizen/complaints', { state: { submittedId: id } })} />} />
    <Route path="*" element={<CitizenOverview complaints={complaints} token={token} summary={summary} loading={loading} user={user} />} />
  </Routes>
}

function SmsPreferences({ token }) {
  const [preferences, setPreferences] = useState(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    let active = true
    api.getNotificationPreferences(token).then((value) => {
      if (active) setPreferences(value)
    }).catch((requestError) => {
      if (active) setError(requestError.message)
    })
    return () => { active = false }
  }, [token])
  const update = async () => {
    if (!preferences) return
    setSaving(true)
    setError('')
    try {
      setPreferences(await api.updateNotificationPreferences(token, {
        sms_consent: !preferences.sms_consent,
      }))
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setSaving(false)
    }
  }
  if (!preferences && !error) return <p className="text-xs text-slate-400">{tr("Loading preferences…")}</p>
  return <div>
    <p className="text-xs text-slate-500">{tr("Phone:")} {preferences?.phone || tr('No phone number is registered')}</p>
    <p className="mt-1 text-xs text-slate-500">{tr("SMS consent:")} {tr(preferences?.sms_consent ? 'On' : 'Off')}</p>
    {preferences?.phone && <button type="button" disabled={saving} onClick={update} className="mt-3 rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 disabled:opacity-50">{tr(saving ? 'Saving…' : preferences.sms_consent ? 'Withdraw consent' : 'Opt in to SMS')}</button>}
    {error && <p role="alert" className="mt-2 text-xs text-rose-600">{tr(error)}</p>}
    <p className="mt-2 text-[10px] leading-4 text-slate-400">{tr("Email and in-app notices are independent of SMS consent. SMS requires an enabled provider.")}</p>
  </div>
}

function CitizenOverview({ complaints, token, summary, loading, user }) {
  const open = summary ? summary.pending + summary.in_progress : complaints.filter((item) => !['Resolved', 'Completed'].includes(item.status)).length
  return <><PageHeading eyebrow="Citizen dashboard" title={tr('Good morning, {{name}}', { name: user?.name?.split(/\s+/)[0] || tr('there') })} description="Here’s what’s happening with your neighborhood today." action={<Link to="/citizen/report" className="inline-flex items-center justify-center gap-2 rounded-xl bg-brand px-4 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-brand-dark"><Plus size={15} /> {tr("Report an issue")}</Link>} />
    <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><StatCard icon={FileText} label="Complaints submitted" value={summary?.total ?? complaints.length} /><StatCard icon={Clock3} label="Awaiting action" value={open} tint="amber" /><StatCard icon={Activity} label="In progress" value={summary?.in_progress ?? complaints.filter((c) => c.status === 'In progress').length} tint="violet" /><StatCard icon={CheckCircle2} label="Successfully resolved" value={summary?.resolved ?? complaints.filter((c) => ['Resolved', 'Completed'].includes(c.status)).length} tint="green" /></div>
    <div className="grid gap-5 xl:grid-cols-[1.55fr_.85fr]"><Panel title={tr("Your recent complaints")} subtitle="Updates from your authenticated account">{loading ? <p className="py-8 text-center text-sm text-slate-400">{tr("Loading your complaints…")}</p> : complaints.length ? <ComplaintTable complaints={complaints.slice(0, 3)} token={token} compact allowFeedback /> : <p className="py-8 text-center text-sm text-slate-500">{tr("No complaints yet. Use “Report an issue” to submit your first one.")}</p>}</Panel><div className="space-y-5"><Panel title={tr("SMS status updates")}><SmsPreferences token={token} /></Panel><Panel title={tr("Your neighborhood")} subtitle="Ward 04 · Lakeview district"><div className="rounded-xl bg-[#eaf2fb] p-4"><div className="flex items-center gap-3"><span className="grid h-10 w-10 place-items-center rounded-xl bg-white text-brand"><MapPin size={18} /></span><div><p className="text-sm font-bold text-ink">{tr("Lakeview district")}</p><p className="text-xs text-slate-500">{tr("Riverdale, Ward 04")}</p></div></div><div className="mt-4 grid grid-cols-2 gap-3"><div className="rounded-xl bg-white p-3"><p className="text-lg font-extrabold text-ink">{summary?.total ?? '—'}</p><p className="text-[10px] text-slate-500">{tr("Your reports")}</p></div><div className="rounded-xl bg-white p-3"><p className="text-lg font-extrabold text-emerald-600">{summary?.resolution_rate ?? 0}%</p><p className="text-[10px] text-slate-500">{tr("Your resolution rate")}</p></div></div></div><div className="mt-4 rounded-xl border border-emerald-100 bg-emerald-50/70 p-3.5"><div className="flex gap-2.5"><Sparkles size={16} className="mt-0.5 shrink-0 text-emerald-600" /><p className="text-xs leading-5 text-emerald-900"><strong>{tr("Neighborhood update")}</strong><br />{tr("Street cleaning is scheduled for Lakeview district tomorrow morning.")}</p></div></div><p className="mt-3 text-center text-[10px] text-slate-400">{tr("Schedule notice is illustrative sample content.")}</p></Panel></div></div>
  </>
}

function CitizenHistory({ complaints, token, loading, onImportLegacy }) {
  const location = useLocation()
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('All')
  const [migrationConfirmed, setMigrationConfirmed] = useState(false)
  const [imported, setImported] = useState(null)
  const [migrationError, setMigrationError] = useState('')
  const [importing, setImporting] = useState(false)
  const [selectedBackup, setSelectedBackup] = useState(null)
  const [selectedBackupName, setSelectedBackupName] = useState('')
  const backup = getLegacyBackup()
  const filtered = useMemo(() => complaints.filter((item) => (filter === 'All' || item.status === filter) && `${item.title} ${item.id} ${item.category}`.toLowerCase().includes(query.toLowerCase())), [complaints, filter, query])
  const migrate = async () => {
    setImporting(true)
    setMigrationError('')
    try {
      const entries = selectedBackup || backup.complaints
      const result = await onImportLegacy(entries)
      setImported(result.count)
      setMigrationConfirmed(false)
    } catch (error) {
      setMigrationError(error.message)
    } finally {
      setImporting(false)
    }
  }
  return <><PageHeading eyebrow="Citizen dashboard" title={tr("My complaints")} description="Every report, update, and resolution in one place." action={<Link to="/citizen/report" className="inline-flex items-center gap-2 rounded-xl bg-brand px-4 py-2.5 text-xs font-bold text-white hover:bg-brand-dark"><Plus size={15} /> {tr("New complaint")}</Link>} />
    {location.state?.submittedId && <div className="mb-5 flex items-start gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800"><CheckCircle2 size={18} className="mt-0.5 shrink-0" /><p><strong>{tr("Complaint submitted!")}</strong> {tr("Your reference number is")} {location.state.submittedId}{tr(". Keep it handy to track progress.")}</p></div>}
    <Panel title={tr("Legacy browser backup")} subtitle="Your old localStorage data remains untouched">
      {backup.error && <p role="alert" className="text-xs text-rose-600">{tr(backup.error)}</p>}
      {!backup.error && backup.complaints.length === 0 && <p className="text-xs leading-5 text-slate-500">{tr("No saved browser complaint backup was found on this origin. Static demo examples are not personal records and are not migrated.")}</p>}
      {!backup.error && backup.complaints.length > 0 && <div className="space-y-3"><p className="text-xs leading-5 text-slate-600">{tr("Found")} {backup.complaints.length} {tr("browser-local records. Download a JSON copy before importing. Legacy entries have no verified citizen ID or authoritative timestamps; importing attributes all selected records to your signed-in citizen account and regenerates their IDs. Your original localStorage backup will not be changed.")}</p><div className="flex flex-wrap items-center gap-3"><button type="button" onClick={() => { try { downloadLegacyBackup(); setMigrationError('') } catch (error) { setMigrationError(error.message) } }} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-bold text-slate-600 hover:bg-slate-50">{tr("Download JSON backup")}</button><label className="cursor-pointer rounded-lg border border-slate-200 px-3 py-2 text-xs font-bold text-slate-600 hover:bg-slate-50">{tr("Choose a backup file")}<input type="file" accept=".json,application/json" className="sr-only" onChange={(event) => { const file = event.target.files?.[0]; if (!file) return; const reader = new FileReader(); reader.onerror = () => setMigrationError('The selected backup file could not be read.'); reader.onload = () => { try { const parsed = JSON.parse(reader.result); const entries = Array.isArray(parsed) ? parsed : parsed?.complaints; if (!Array.isArray(entries) || !entries.length) throw new Error('Choose a JSON backup containing a non-empty complaints array.'); setSelectedBackup(entries); setSelectedBackupName(file.name); setMigrationError('') } catch (error) { setSelectedBackup(null); setSelectedBackupName(''); setMigrationError(error.message) } }; reader.readAsText(file) }} /></label>{selectedBackupName && <span className="text-xs text-slate-500">{tr("Selected:")} {selectedBackupName} ({selectedBackup.length})</span>}<label className="flex items-center gap-2 text-xs text-slate-600"><input type="checkbox" checked={migrationConfirmed} onChange={(event) => setMigrationConfirmed(event.target.checked)} /> {tr("I reviewed the backup and want to import every record into this account.")}</label><button type="button" disabled={!migrationConfirmed || importing || imported !== null || !(selectedBackup || backup.complaints).length} onClick={migrate} className="rounded-lg bg-brand px-3 py-2 text-xs font-bold text-white hover:bg-brand-dark disabled:cursor-not-allowed disabled:opacity-50">{tr(importing ? 'Importing…' : 'Import this backup')}</button></div></div>}
      {!backup.error && backup.complaints.length === 0 && <div className="mt-3"><label className="cursor-pointer rounded-lg border border-slate-200 px-3 py-2 text-xs font-bold text-slate-600 hover:bg-slate-50">{tr("Choose an exported backup")}<input type="file" accept=".json,application/json" className="sr-only" onChange={(event) => { const file = event.target.files?.[0]; if (!file) return; const reader = new FileReader(); reader.onerror = () => setMigrationError('The selected backup file could not be read.'); reader.onload = () => { try { const parsed = JSON.parse(reader.result); const entries = Array.isArray(parsed) ? parsed : parsed?.complaints; if (!Array.isArray(entries) || !entries.length) throw new Error('Choose a JSON backup containing a non-empty complaints array.'); setSelectedBackup(entries); setSelectedBackupName(file.name); setMigrationError('') } catch (error) { setSelectedBackup(null); setSelectedBackupName(''); setMigrationError(error.message) } }; reader.readAsText(file) }} /></label>{selectedBackup && <div className="mt-3 flex flex-wrap items-center gap-3"><span className="text-xs text-slate-500">{selectedBackupName} ({selectedBackup.length} {tr("complaints)")}</span><label className="flex items-center gap-2 text-xs text-slate-600"><input type="checkbox" checked={migrationConfirmed} onChange={(event) => setMigrationConfirmed(event.target.checked)} /> {tr("Import every record into this account after reviewing the backup.")}</label><button type="button" disabled={!migrationConfirmed || importing || imported !== null} onClick={migrate} className="rounded-lg bg-brand px-3 py-2 text-xs font-bold text-white hover:bg-brand-dark disabled:cursor-not-allowed disabled:opacity-50">{tr(importing ? 'Importing…' : 'Import selected backup')}</button></div>}</div>}
      {imported !== null && <p role="status" className="mt-3 text-xs text-emerald-700">{tr(imported === 1 ? 'Imported {{count}} complaint into your account. The original browser backup was kept.' : 'Imported {{count}} complaints into your account. The original browser backup was kept.', { count: imported })}</p>}
      {migrationError && <p role="alert" className="mt-3 text-xs text-rose-600">{tr(migrationError)}</p>}
    </Panel>
    <Panel title={tr("Complaint history")} subtitle="Your authenticated records update automatically while this dashboard is open">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row"><div className="relative flex-1"><Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={tr("Search by title, ID, or category")} className="w-full rounded-xl border border-slate-200 py-2.5 pl-9 pr-3 text-xs outline-none focus:border-brand" /></div>            <select value={filter} onChange={(event) => setFilter(event.target.value)} className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-xs text-slate-600 outline-none focus:border-brand">{['All', 'Pending', 'Accepted', 'In progress', 'Completed', 'Resolved'].map((status) => <option key={status} value={status}>{tr(status)}</option>)}</select></div>
      {loading ? <p className="py-8 text-center text-sm text-slate-400">{tr("Loading complaint history…")}</p> : filtered.length ? <ComplaintTable complaints={filtered} token={token} allowFeedback /> : <div className="py-10 text-center text-sm text-slate-500">{tr(complaints.length ? 'No complaints match your search.' : 'No complaints yet. Submitted reports will appear here.')}</div>}
    </Panel></>
}

function MunicipalAnalyticsPanel({ token }) {
  const [analytics, setAnalytics] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    api.getMunicipalAnalytics(token).then((value) => {
      if (active) setAnalytics(value)
    }).catch((requestError) => {
      if (active) setError(requestError.message)
    })
    return () => { active = false }
  }, [token])
  return <Panel title={tr("Workload & escalation visibility")} subtitle="Read-only citywide monitoring · GPS clusters use submitted coordinates only">
    {error && <p role="alert" className="text-xs text-rose-600">{tr(error)}</p>}
    {!analytics && !error && <p className="text-xs text-slate-400">{tr("Loading municipal analytics…")}</p>}
    {analytics && <div className="grid gap-5 lg:grid-cols-2">
      <div><h3 className="mb-2 text-xs font-bold text-ink">{tr("Department workload")}</h3><div className="space-y-2">{analytics.departments.map((item) => <div key={item.department} className="flex items-center justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2 text-[10px]"><span className="font-semibold text-slate-700">{item.department}</span><span className="text-slate-500">{item.total} {tr("total ·")} {item.pending} {tr("pending ·")} {item.in_progress} {tr("active ·")} {item.completed} {tr("complete ·")} {item.overdue} {tr("overdue")}</span></div>)}</div></div>
      <div><h3 className="mb-2 text-xs font-bold text-ink">{tr("Escalations")}</h3>{analytics.escalations.length ? <ul className="space-y-2">{analytics.escalations.slice(0, 8).map((item) => <li key={item.complaint_id} className="rounded-lg border border-amber-100 bg-amber-50/60 px-3 py-2 text-[10px] text-slate-600"><strong className="text-ink">{item.complaint_id}</strong> · {tr(item.assigned_department)} · {tr(item.status)}{item.overdue ? ` · ${tr('overdue')}` : ''}{item.expected_completion_at && <span> {tr("· ETA")} {displayDate(item.expected_completion_at)}</span>}</li>)}</ul> : <p className="text-xs text-slate-500">{tr("No current escalations.")}</p>}
        <h3 className="mb-2 mt-4 text-xs font-bold text-ink">{tr("GPS hotspots")}</h3>{analytics.hotspots.length ? analytics.hotspots.map((item) => <p key={`${item.latitude}-${item.longitude}`} className="text-[10px] text-slate-500">{item.count} {tr("reports near")} {item.latitude}, {item.longitude}</p>) : <p className="text-[10px] text-slate-500">{tr("No repeated coordinate clusters.")} {analytics.gps_complaints} {tr("reports include GPS.")}</p>}
        <p className="mt-1 text-[9px] text-slate-400">{analytics.gps_hotspot_precision}</p>
      </div>
    </div>}
  </Panel>
}

function AdminDeliveryMonitor({ token }) {
  const [deliveries, setDeliveries] = useState([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(null)
  const refresh = async () => {
    try {
      const result = await api.getNotificationDeliveries(token)
      setDeliveries(result.deliveries)
      setError('')
    } catch (requestError) {
      setError(requestError.message)
    }
  }
  useEffect(() => { refresh() }, [token])
  const retry = async (id) => {
    setBusy(id)
    try {
      await api.retryNotificationDelivery(token, id)
      await refresh()
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy(null)
    }
  }
  return <Panel title={tr("Notification delivery log")} subtitle="Admin-only retries; check the provider before retrying an ambiguous timeout">
    {error && <p role="alert" className="mb-2 text-xs text-rose-600">{tr(error)}</p>}
    {deliveries.length ? <div className="space-y-2">{deliveries.slice(0, 8).map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-slate-50 px-3 py-2 text-[10px]"><span><strong>{tr(item.channel)}</strong> · {item.complaint_id} · {tr(({ pending: 'Pending', sent: 'Sent', delivered: 'Delivered', failed: 'Failed', not_configured: 'Failed · Not configured', skipped: 'Skipped · No consent' })[item.status] || 'Failed')} {tr("· Updated")} {displayDate(item.updated_at)}{item.failure_detail && <span className="ml-1 text-rose-600">{item.failure_detail}</span>}</span>{['failed', 'not_configured'].includes(item.status) && <button type="button" disabled={busy === item.id} onClick={() => retry(item.id)} className="rounded border border-slate-200 px-2 py-1 font-semibold text-slate-600 disabled:opacity-50">{tr(busy === item.id ? 'Retrying…' : 'Retry')}</button>}</div>)}</div> : !error && <p className="text-xs text-slate-500">{tr("No delivery records yet.")}</p>}
  </Panel>
}

function CategoryMappingPanel({ token }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const refresh = async () => {
    try {
      setData(await api.getCategoryMappings(token))
      setError('')
    } catch (requestError) {
      setError(requestError.message)
    }
  }
  useEffect(() => { refresh() }, [token])
  return <Panel title={tr("Verified category routing")} subtitle="Complaints follow the fixed category-to-department routing shown below.">
    {error && <p role="alert" className="mb-2 text-xs text-rose-600">{tr(error)}</p>}
    {!data && !error && <p className="text-xs text-slate-400">{tr("Loading verified mappings…")}</p>}
    {data && <div className="space-y-2">{data.mappings.map((item) => <div key={item.category} className="grid gap-2 rounded-lg bg-slate-50 p-2 sm:grid-cols-[1fr_1fr] sm:items-center"><span className="text-xs font-semibold text-ink">{tr(item.category)}</span><span className="text-xs text-slate-600">{tr(item.department)}</span></div>)}
      <details className="pt-2 text-[10px]"><summary className="cursor-pointer font-semibold text-slate-600">{tr("Recent mapping audit history")}</summary><ul className="mt-2 space-y-1">{data.history.map((entry, index) => <li key={`${entry.category}-${entry.changed_at}-${index}`} className="text-slate-500">{entry.category}: {entry.old_department || 'unmapped'} → {entry.new_department} · {entry.changed_by} · {entry.reason}</li>)}</ul></details>
    </div>}
  </Panel>
}

function AdminModelMonitor({ token }) {
  const [metrics, setMetrics] = useState(null)
  const [dataset, setDataset] = useState(null)
  const [error, setError] = useState('')
  const [formError, setFormError] = useState('')
  const [busy, setBusy] = useState(false)
  const load = async () => {
    try {
      const [evaluation, records] = await Promise.all([
        api.getMlMetrics(token), api.getVerifiedDataset(token),
      ])
      setMetrics(evaluation)
      setDataset(records)
      setError('')
    } catch (requestError) {
      setError(requestError.message)
    }
  }
  useEffect(() => { load() }, [token])
  const addExample = async (event) => {
    event.preventDefault()
    setBusy(true)
    setFormError('')
    const formElement = event.currentTarget
    const form = new FormData(formElement)
    try {
      const complaintId = String(form.get('complaint_id') || '').trim()
      await api.addVerifiedExample(token, {
        category: form.get('category'),
        verification_note: form.get('verification_note'),
        ...(complaintId ? { complaint_id: complaintId } : { description: form.get('description') }),
      })
      formElement.reset()
      await load()
    } catch (requestError) {
      setFormError(requestError.message)
    } finally {
      setBusy(false)
    }
  }
  const removeExample = async (id) => {
    setBusy(true)
    setFormError('')
    try {
      await api.deleteVerifiedExample(token, id)
      await load()
    } catch (requestError) {
      setFormError(requestError.message)
    } finally {
      setBusy(false)
    }
  }
  const categories = ['Roads & pathways', 'Waste management', 'Water supply', 'Street lighting', 'Drainage & flooding', 'Public health', 'Parks & gardens', 'Other']
  return <Panel title={tr("Verified training dataset & model evaluation")} subtitle="Only municipal-verified labels are used. Training and evaluation never control complaint routing.">
    {error && <p role="alert" className="text-xs text-rose-600">{tr(error)}</p>}
    {formError && <p role="alert" className="text-xs text-rose-600">{tr(formError)}</p>}
    {!metrics && !error && <p className="text-xs text-slate-400">{tr("Loading verified dataset…")}</p>}
    {metrics && <div className="space-y-2 text-xs text-slate-600">
      <p>{tr("Model state:")} <strong>{metrics.status === 'insufficient_data' ? tr('Insufficient verified data') : tr(metrics.evaluation)}</strong> · {metrics.evaluated_samples} {tr("evaluated of")} {metrics.training_samples} {tr("verified labels.")}</p>
      <p>{tr("Verified examples per category:")} {Object.entries(metrics.category_counts || {}).map(([category, count]) => `${category}: ${count}`).join(' · ') || 'none'} · {metrics.minimum_examples_per_category} {tr("per category required.")}</p>
      <div className="grid grid-cols-2 gap-2"><p>{tr("Accuracy:")} {metrics.accuracy == null ? '—' : `${Math.round(metrics.accuracy * 100)}%`}</p><p>{tr("Macro precision:")} {metrics.macro_precision == null ? '—' : `${Math.round(metrics.macro_precision * 100)}%`}</p><p>{tr("Macro recall:")} {metrics.macro_recall == null ? '—' : `${Math.round(metrics.macro_recall * 100)}%`}</p><p>{tr("Macro F1:")} {metrics.macro_f1 == null ? '—' : `${Math.round(metrics.macro_f1 * 100)}%`}</p></div>
      <p className="text-[10px] leading-4 text-amber-700">{metrics.limitations}</p>
      <p className="text-[9px] text-slate-400">{tr("No model reliability claim is made. The citizen-selected category and verified mapping always control routing.")}</p>
      {metrics.confusion_matrix && <details className="text-[10px]"><summary className="cursor-pointer font-semibold">{tr("Confusion matrix")}</summary><pre className="mt-1 overflow-x-auto rounded bg-slate-50 p-2">{JSON.stringify(metrics.confusion_matrix, null, 2)}</pre></details>}
    </div>}
    <form onSubmit={addExample} className="mt-4 grid gap-2 border-t border-slate-100 pt-4 sm:grid-cols-2">
      <select name="category" required className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs">{categories.map((category) => <option key={category} value={category}>{tr(category)}</option>)}{dataset?.examples && [...new Set(dataset.examples.map((item) => item.category))].filter((category) => !categories.includes(category)).map((category) => <option key={category} value={category}>{tr(category)}</option>)}</select>
      <input name="complaint_id" placeholder={tr("Existing complaint ID (optional)")} className="rounded-lg border border-slate-200 px-3 py-2 text-xs" />
      <textarea name="description" minLength={10} maxLength={1200} placeholder={tr("Verified complaint description (leave blank when using an ID)")} className="rounded-lg border border-slate-200 px-3 py-2 text-xs sm:col-span-2" />
      <input name="verification_note" required minLength={5} maxLength={500} placeholder={tr("How was this category verified?")} className="rounded-lg border border-slate-200 px-3 py-2 text-xs" />
      <button disabled={busy} className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700 disabled:opacity-50">{tr(busy ? 'Saving…' : 'Add verified label')}</button>
    </form>
    <div className="mt-3 flex flex-wrap items-center justify-between gap-2"><p className="text-[10px] text-slate-500">{dataset?.examples?.length ?? 0} {tr("verified examples stored.")}</p><p className="text-[10px] text-slate-500">{tr("Model retraining is disabled.")}</p></div>
    {dataset?.examples?.length > 0 && <div className="mt-3 max-h-40 space-y-1 overflow-y-auto">{dataset.examples.map((example) => <div key={example.id} className="flex items-start justify-between gap-2 rounded bg-slate-50 px-2 py-1.5 text-[10px]"><span><strong>{tr(example.category)}</strong> · {example.source_complaint_id || tr('manual label')} · {example.verification_note}</span><button type="button" disabled={busy} onClick={() => removeExample(example.id)} className="shrink-0 font-semibold text-rose-600 disabled:opacity-50">{tr("Remove")}</button></div>)}</div>}
  </Panel>
}

function ReportForm({ addComplaint, onDone }) {
  const [photo, setPhoto] = useState(null)
  const [locationMessage, setLocationMessage] = useState('')
  const [locationError, setLocationError] = useState('')
  const [uploadError, setUploadError] = useState('')
  const [submitError, setSubmitError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const getLocation = () => {
    if (!navigator.geolocation) { setLocationMessage('Location is not supported in this browser. Enter an address manually.'); return }
    setLocationMessage('Requesting your location…')
    navigator.geolocation.getCurrentPosition((position) => {
      document.getElementById('latitude').value = position.coords.latitude.toFixed(6)
      document.getElementById('longitude').value = position.coords.longitude.toFixed(6)
      setLocationMessage('Location added. You can still enter a street address below.')
    }, (error) => setLocationMessage(error.code === error.PERMISSION_DENIED ? 'Location permission was denied. Enter your location manually.' : 'Could not get your location. Please enter it manually.'), { timeout: 10000 })
  }
  const submit = async (event) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const address = form.get('address').trim()
    const latitude = form.get('latitude').trim()
    const longitude = form.get('longitude').trim()
    if (!address && !(latitude && longitude)) {
      setLocationError('Enter a street address or provide both GPS coordinates.')
      return
    }
    setLocationError('')
    setSubmitError('')
    setSubmitting(true)
    try {
      const entry = await addComplaint({
        title: form.get('title').trim(),
        category: form.get('category'),
        location: address || `GPS: ${latitude}, ${longitude}`,
        latitude,
        longitude,
        description: form.get('description').trim(),
        image: photo,
      })
      onDone(entry.id)
    } catch (error) {
      setSubmitError(error.message)
    } finally {
      setSubmitting(false)
    }
  }
  return <><PageHeading eyebrow="Citizen dashboard" title={tr("Report a civic issue")} description="Give your city team the details they need to put things right." />
    <div className="grid items-start gap-5 xl:grid-cols-[1fr_320px]">
      <form onSubmit={submit} className="space-y-5 rounded-2xl border border-slate-100 bg-white p-5 shadow-card sm:p-7">
        <div className="flex items-start gap-3 rounded-xl bg-blue-50 p-4"><span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-white text-brand"><ShieldCheck size={17} /></span><p className="text-xs leading-5 text-blue-900"><strong>{tr("Help us help you.")}</strong> {tr("Accurate details and a nearby landmark help the right department respond faster.")}</p></div>
        <div><label className="mb-1.5 block text-xs font-bold text-slate-700">{tr("Complaint title")} <span className="text-rose-500">*</span></label><input name="title" required maxLength="100" placeholder={tr("Briefly describe the issue")} className="w-full rounded-xl border border-slate-200 px-4 py-3 text-sm outline-none placeholder:text-slate-400 focus:border-brand focus:ring-4 focus:ring-blue-50" /></div>
        <div><label className="mb-1.5 block text-xs font-bold text-slate-700">{tr("Category")} <span className="text-rose-500">*</span></label><select name="category" required defaultValue="" className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600 outline-none focus:border-brand"><option value="" disabled>{tr("Select the closest category")}</option>{['Roads & pathways', 'Waste management', 'Water supply', 'Street lighting', 'Drainage & flooding', 'Public health', 'Parks & gardens', 'Other'].map((category) => <option key={category} value={category}>{tr(category)}</option>)}</select></div>
        <div><label className="mb-1.5 block text-xs font-bold text-slate-700">{tr("Description")} <span className="font-normal text-slate-400">{tr("(optional when a photo is attached)")}</span></label><textarea name="description" maxLength="1200" rows="4" placeholder={tr("Describe what happened, when you noticed it, and anything else that could help...")} className="w-full resize-y rounded-xl border border-slate-200 px-4 py-3 text-sm outline-none placeholder:text-slate-400 focus:border-brand focus:ring-4 focus:ring-blue-50" /><p className="mt-1 text-right text-[10px] text-slate-400">{tr("Add at least 10 characters unless you attach a photo. Please don't include sensitive personal information.")}</p></div>
        <div><label className="mb-1.5 block text-xs font-bold text-slate-700">{tr("Photo evidence")} <span className="font-normal text-slate-400">{tr("(optional)")}</span></label><label className="flex cursor-pointer items-center gap-3 rounded-xl border border-dashed border-slate-300 bg-slate-50/60 p-4 transition hover:border-brand hover:bg-blue-50/40"><span className="grid h-10 w-10 place-items-center rounded-xl bg-white text-brand shadow-sm"><ImagePlus size={19} /></span><span className="min-w-0 flex-1"><span className="block text-xs font-semibold text-slate-700">{photo?.name || tr('Upload a photo')}</span><span className="mt-1 block text-[10px] text-slate-400">{tr("JPG, PNG, or WebP · up to 5 MB")}</span></span><input type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" onChange={async (event) => { const file = event.target.files?.[0]; setPhoto(null); setUploadError(''); if (!file) return; try { const data = await compressComplaintImage(file); setPhoto({ name: file.name, data }) } catch (error) { setUploadError(error.message) } }} /></label>{uploadError && <p role="alert" className="mt-2 text-xs text-rose-600">{tr(uploadError)}</p>}{photo?.data && <img src={photo.data} alt={tr("Selected complaint evidence preview")} className="mt-3 max-h-36 rounded-xl object-cover" />}</div>
        <div><div className="mb-1.5 flex flex-wrap items-center justify-between gap-2"><label className="text-xs font-bold text-slate-700">{tr("Location")} <span className="text-rose-500">*</span></label><button type="button" onClick={getLocation} className="inline-flex items-center gap-1.5 text-xs font-bold text-brand hover:text-brand-dark"><LocateFixed size={14} /> {tr("Use my current location")}</button></div><input id="address" name="address" placeholder={tr("Street, area, or nearby landmark")} className="w-full rounded-xl border border-slate-200 px-4 py-3 text-sm outline-none placeholder:text-slate-400 focus:border-brand focus:ring-4 focus:ring-blue-50" /><div className="mt-2 grid grid-cols-2 gap-3"><input id="latitude" name="latitude" aria-label={tr("Latitude")} placeholder={tr("Latitude (optional)")} className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-xs outline-none placeholder:text-slate-400 focus:border-brand" /><input id="longitude" name="longitude" aria-label={tr("Longitude")} placeholder={tr("Longitude (optional)")} className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-xs outline-none placeholder:text-slate-400 focus:border-brand" /></div>{locationError && <p role="alert" className="mt-2 text-xs text-rose-600">{tr(locationError)}</p>}{locationMessage && <p role="status" className="mt-2 text-xs text-slate-500">{tr(locationMessage)}</p>}</div>
        {submitError && <p role="alert" className="text-xs text-rose-600">{tr(submitError)}</p>}
        <div className="flex flex-col-reverse gap-3 border-t border-slate-100 pt-5 sm:flex-row sm:justify-end"><Link to="/citizen" className="rounded-xl border border-slate-200 px-5 py-3 text-center text-xs font-bold text-slate-600 hover:bg-slate-50">{tr("Cancel")}</Link><button disabled={submitting} type="submit" className="inline-flex items-center justify-center gap-2 rounded-xl bg-brand px-5 py-3 text-xs font-bold text-white shadow-sm hover:bg-brand-dark disabled:opacity-60">{tr(submitting ? 'Submitting…' : 'Submit complaint')} <ArrowRight size={15} /></button></div>
      </form>
      <div className="space-y-4"><Panel title={tr("What happens next?")}><div className="space-y-4">{[['1', 'Your report is logged', 'You receive a unique complaint ID to track progress.'], ['2', 'The right team is notified', 'Your report is routed to the relevant city department.'], ['3', 'You get status updates', 'Follow progress through your complaint history.']].map(([number, title, text]) => <div key={number} className="flex gap-3"><span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-blue-50 text-xs font-bold text-brand">{number}</span><div><p className="text-xs font-bold text-ink">{tr(title)}</p><p className="mt-1 text-[11px] leading-4 text-slate-500">{tr(text)}</p></div></div>)}</div></Panel><div className="rounded-2xl border border-slate-100 bg-white p-5 shadow-card"><div className="flex gap-3"><Lightbulb size={18} className="shrink-0 text-amber-500" /><div><p className="text-xs font-bold text-ink">{tr("Reporting tip")}</p><p className="mt-1.5 text-xs leading-5 text-slate-500">{tr("One issue per report helps us assign it to the right team and resolve it more quickly.")}</p></div></div></div>      <p className="px-2 text-center text-[10px] text-slate-400">{tr("Submitted directly to the authenticated Flask API.")}</p></div>
    </div>
  </>
}

function DepartmentChart({ complaints }) {
  const colors = ['#2463eb', '#43b89c', '#f5a623', '#8b70e8', '#9aabc2', '#ef7891', '#56a7bb']
  const data = Object.entries(complaints.reduce((counts, item) => {
    counts[item.category] = (counts[item.category] || 0) + 1
    return counts
  }, {})).map(([name, value], index) => ({ name: tr(name), value, color: colors[index % colors.length] }))
  return <ResponsiveContainer width="100%" height={250}><PieChart><Pie data={data} dataKey="value" nameKey="name" innerRadius={62} outerRadius={93} paddingAngle={4} stroke="none">{data.map((entry) => <Cell key={entry.name} fill={entry.color} />)}</Pie><Tooltip formatter={(value) => [`${value} ${tr('reports')}`, tr('Complaints')]} /><text x="50%" y="47%" textAnchor="middle" className="fill-ink" fontSize="23" fontWeight="800">{complaints.length}</text><text x="50%" y="58%" textAnchor="middle" className="fill-slate-400" fontSize="10">{tr("complaints")}</text></PieChart></ResponsiveContainer>
}

function MunicipalDashboard({ complaints, token, summary, loading }) {
  return <Routes><Route index element={<MunicipalOverview complaints={complaints} token={token} summary={summary} loading={loading} />} /><Route path="complaints" element={<MunicipalComplaints complaints={complaints} token={token} loading={loading} />} /><Route path="departments" element={<DepartmentOverview complaints={complaints} />} /><Route path="*" element={<MunicipalOverview complaints={complaints} token={token} summary={summary} loading={loading} />} /></Routes>
}

function MunicipalOverview({ complaints, token, summary, loading }) {
  const count = (status) => complaints.filter((item) => status === 'Pending'
    ? ['Pending', 'Accepted'].includes(item.status)
    : status === 'Resolved' ? ['Resolved', 'Completed'].includes(item.status)
      : item.status === status).length
  const categories = Object.entries(complaints.reduce((counts, item) => {
    counts[item.category] = (counts[item.category] || 0) + 1
    return counts
  }, {}))
  const recommendationCategories = [...new Set(complaints.map((item) =>
    typeof item.category === 'string' && item.category.trim() ? item.category.trim() : 'Uncategorized'
  ))].slice(0, 3)
  const needsReview = summary?.needs_review ?? complaints.filter((item) => item.assignment_review_required).length
  return <><PageHeading eyebrow="Municipal dashboard" title={tr("Operations overview")} description="Monitor incoming reports and coordinate your response." action={<button className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-xs font-bold text-slate-600 hover:border-blue-200"><span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> {tr("Live operations")} <ChevronDown size={14} /></button>} />
    <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-5"><StatCard icon={FileText} label="Total complaints" value={complaints.length} footnote="Authenticated backend records" /><StatCard icon={Clock3} label="Pending review" value={count('Pending')} tint="amber" /><StatCard icon={Activity} label="In progress" value={count('In progress')} tint="violet" /><StatCard icon={CheckCircle2} label="Completed complaints" value={count('Resolved')} tint="green" /><StatCard icon={CircleHelp} label="Needs assignment review" value={needsReview} tint="amber" /></div>
    <div className="mb-5"><MunicipalAnalyticsPanel token={token} /></div>
    <div className="mb-5"><CategoryMappingPanel token={token} /></div>
    <div className="mb-5 grid gap-5 xl:grid-cols-[1.4fr_.8fr]"><Panel title={tr("Complaint volume by month")} subtitle="Received and resolved reports · Last six months"><ResponsiveContainer width="100%" height={260}><BarChart data={summary?.monthly || []} barGap={6} margin={{ top: 5, right: 2, left: -22, bottom: 0 }}><CartesianGrid stroke="#eef2f7" vertical={false} /><XAxis dataKey="month" axisLine={false} tickLine={false} tick={{ fill: '#8b98aa', fontSize: 11 }} dy={8} /><YAxis axisLine={false} tickLine={false} tick={{ fill: '#8b98aa', fontSize: 10 }} /><Tooltip contentStyle={{ borderRadius: 12, border: '1px solid #e9eef5', fontSize: 12 }} /><Bar dataKey="received" name="Received" fill="#b9d2ff" radius={[5, 5, 0, 0]} /><Bar dataKey="resolved" name="Resolved" fill="#2463eb" radius={[5, 5, 0, 0]} /></BarChart></ResponsiveContainer><div className="mt-1 flex justify-center gap-5 text-[10px] text-slate-500"><span><i className="mr-1.5 inline-block h-2 w-2 rounded-sm bg-blue-200" />{tr("Received")}</span><span><i className="mr-1.5 inline-block h-2 w-2 rounded-sm bg-brand" />{tr("Resolved")}</span></div></Panel>
      <Panel title={tr("Complaints by category")} subtitle="Categories in the shared complaint list"><div className="relative"><DepartmentChart complaints={complaints} /></div><div className="grid grid-cols-2 gap-x-3 gap-y-2">{categories.map(([name, value], index) => <div key={name} className="flex items-center justify-between gap-1 text-[10px]"><span className="flex items-center gap-1.5 text-slate-500"><i className="h-2 w-2 rounded-full" style={{ background: ['#2463eb', '#43b89c', '#f5a623', '#8b70e8', '#9aabc2', '#ef7891', '#56a7bb'][index % 7] }} />{tr(name)}</span><strong className="text-ink">{value}</strong></div>)}</div></Panel></div>
    <Panel title={tr("Recent complaints")} subtitle="Read-only monitoring across all departments" action={<Link to="/municipal/complaints" className="text-xs font-bold text-brand">{tr("View queue")} <ArrowRight size={13} className="ml-1 inline" /></Link>}>{loading ? <p className="py-8 text-center text-sm text-slate-400">{tr("Loading current complaints…")}</p> : complaints.length ? <ComplaintTable complaints={complaints} token={token} showCitizen /> : <p className="py-8 text-center text-sm text-slate-500">{tr("No complaints have been submitted yet.")}</p>}</Panel>
    <div className="mt-5 rounded-2xl border border-violet-100 bg-gradient-to-r from-violet-50 to-blue-50 p-5 sm:p-6"><div className="flex items-start gap-3"><span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-white text-violet-600 shadow-sm"><Sparkles size={19} /></span><div className="flex-1"><div className="flex flex-wrap items-center gap-2"><h2 className="font-display text-sm font-bold text-ink">{tr("AI recommendations")}</h2><span className="rounded-full bg-violet-100 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-violet-700">{tr("Rule-based preview")}</span></div><p className="mt-1 text-xs text-slate-500">{tr("Suggested departments and next actions from complaint categories. This is demo logic, not a live AI model.")}</p><div className="mt-4 grid gap-3 md:grid-cols-3">{recommendationCategories.map((category) => { const suggestion = getCategoryAdvice(category); return <Recommendation key={category} icon={<ArrowUpRight size={14} />} category={category} department={suggestion.department} action={suggestion.action} tone="violet" /> })}</div></div></div></div>
  </>
}

function Recommendation({ icon, category, department, action, tone }) { const styles = { violet: 'text-violet-700 bg-violet-100', amber: 'text-amber-700 bg-amber-100', blue: 'text-blue-700 bg-blue-100' }; return <div className="flex items-start gap-2.5 rounded-xl border border-white/80 bg-white/80 p-3"><span className={cx('mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-lg', styles[tone])}>{icon}</span><p className="text-[11px] leading-5 text-slate-600">{tr('{{category}}: assign to {{department}}. {{action}}', { category: tr(category), department: tr(department), action: tr(action) })}</p></div> }

function MunicipalComplaints({ complaints, token, loading, assignDepartment, updatePriority, admin = false }) {
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('All categories')
  const [status, setStatus] = useState('All statuses')
  const categories = [...new Set(complaints.map((item) => item.category))]
  const filtered = complaints.filter((item) =>
    (category === 'All categories' || item.category === category)
    && (status === 'All statuses' || item.status === status)
    && `${item.title} ${item.id} ${item.category} ${item.citizen} ${item.description}`.toLowerCase().includes(query.toLowerCase()))
  return <><PageHeading eyebrow={admin ? 'Admin dashboard' : 'Municipal dashboard'} title={tr("Complaint queue")} description={tr(admin ? 'Monitor complaints and coordinate department assignment.' : 'Read-only monitoring, workload tracking, and escalation visibility across all departments.')} /><Panel title={tr("All incoming complaints")} subtitle={tr('{{count}} reports shown · {{mode}}', { count: filtered.length, mode: tr(admin ? 'Admin assignment controls' : 'Read-only live API data') })}><div className="mb-4 grid gap-3 sm:grid-cols-[minmax(200px,1fr)_auto_auto]"><div className="relative"><Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={tr("Search reports, citizens, descriptions...")} className="w-full rounded-xl border border-slate-200 py-2.5 pl-9 pr-3 text-xs outline-none focus:border-brand" /></div><select aria-label={tr("Filter by category")} value={category} onChange={(event) => setCategory(event.target.value)} className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-xs text-slate-600 outline-none focus:border-brand"><option value="All categories">{tr("All categories")}</option>{categories.map((value) => <option key={value} value={value}>{tr(value)}</option>)}</select><select aria-label={tr("Filter by status")} value={status} onChange={(event) => setStatus(event.target.value)} className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-xs text-slate-600 outline-none focus:border-brand"><option value="All statuses">{tr("All statuses")}</option>{['Pending', 'Accepted', 'In progress', 'Completed', 'Resolved'].map((value) => <option key={value} value={value}>{tr(value)}</option>)}</select></div>{loading ? <p className="py-8 text-center text-sm text-slate-400">{tr("Loading complaint queue…")}</p> : filtered.length ? <ComplaintTable complaints={filtered} token={token} showCitizen {...(assignDepartment ? { onAssign: assignDepartment } : {})} {...(updatePriority ? { onPriorityChange: updatePriority } : {})} /> : <p className="py-8 text-center text-sm text-slate-500">{complaints.length ? tr('No complaints match these filters.') : tr('No complaints have been submitted yet.')}</p>}</Panel></>
}

function DepartmentDashboard({ complaints, updateDepartmentComplaint, token, loading, user }) {
  const departmentComplaints = complaints.filter(
    (item) => item.assigned_department === user?.department,
  )
  const [notes, setNotes] = useState({})
  const [etaValues, setEtaValues] = useState({})
  const [busy, setBusy] = useState('')
  const [history, setHistory] = useState({})
  const [historyLoading, setHistoryLoading] = useState('')
  const [historyError, setHistoryError] = useState('')
  const [openHistory, setOpenHistory] = useState({})
  const loadHistory = async (complaintId) => {
    setHistoryLoading(complaintId)
    setHistoryError('')
    try {
      const result = await api.getComplaintHistory(token, complaintId)
      setHistory((current) => ({ ...current, [complaintId]: result.history }))
    } catch (error) {
      setHistoryError(error.message)
    } finally {
      setHistoryLoading('')
    }
  }
  const perform = async (item, updates) => {
    setBusy(item.id)
    try {
      const updated = await updateDepartmentComplaint(item.id, updates)
      if (updated) {
        if (updates.note) {
          setNotes((current) => ({ ...current, [item.id]: '' }))
        }
        setHistory((current) => ({ ...current, [item.id]: null }))
        if (openHistory[item.id]) await loadHistory(item.id)
      }
    } finally {
      setBusy('')
    }
  }
  const toggleHistory = async (item) => {
    if (openHistory[item.id]) {
      setOpenHistory((current) => ({ ...current, [item.id]: false }))
      return
    }
    setOpenHistory((current) => ({ ...current, [item.id]: true }))
    setHistoryError('')
    if (history[item.id]) return
    await loadHistory(item.id)
  }
  const pendingCount = departmentComplaints.filter((item) => ['Pending', 'Accepted'].includes(item.status)).length
  const completedCount = departmentComplaints.filter((item) => ['Completed', 'Resolved'].includes(item.status)).length
  return <><PageHeading eyebrow={tr("Department dashboard")} title={`${user?.department || tr('Department')} ${tr('queue')}`} description={tr("Review only the complaints assigned to your department and record work progress.")} />
    <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard icon={FileText} label="Assigned complaints" value={departmentComplaints.length} />
      <StatCard icon={Clock3} label="Pending complaints" value={pendingCount} tint="amber" />
      <StatCard icon={Activity} label="Active work" value={departmentComplaints.filter((item) => item.status === 'In progress').length} tint="violet" />
      <StatCard icon={CheckCircle2} label="Completed complaints" value={completedCount} tint="green" />
    </div>
    <Panel title={tr("Assigned complaints")} subtitle={tr('{{count}} complaints · Department-restricted API', { count: departmentComplaints.length })}>
      {loading ? <p className="py-8 text-center text-sm text-slate-400">{tr("Loading assigned complaints…")}</p> : departmentComplaints.length ? <div className="space-y-4">{departmentComplaints.map((item) => {
        const nextAction = item.status === 'Pending'
          ? { action: 'accept', label: 'Accept complaint' }
          : item.status === 'Accepted'
            ? { action: 'in_progress', label: 'Start work' }
            : item.status === 'In progress'
              ? { action: 'complete', label: 'Mark completed' }
              : null
        return <article key={item.id} className="rounded-2xl border border-slate-100 p-4 sm:p-5">
          <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{item.id} · {tr(item.category)}</p><h3 className="mt-1 text-sm font-bold text-ink">{item.title}</h3><p className="mt-1 text-xs text-slate-500">{item.location} {tr("· Reported by")} {item.citizen}</p><p className="mt-1 text-[10px] text-slate-400">{tr("Submitted")} {displayDate(item.created_at || item.date)}</p></div><span className={cx('rounded-full px-2.5 py-1 text-[10px] font-bold ring-1 ring-inset', statusStyle[item.status] || statusStyle.Pending)}>{tr(item.status)}</span></div>
          <div className="mt-3 flex flex-wrap items-start gap-4"><div className="min-w-0 flex-1"><p className="text-xs leading-5 text-slate-600">{item.description || 'No text description provided; see attached photo.'}</p>{item.latest_progress_note && <div className="mt-3 rounded-xl bg-slate-50 p-3"><p className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{tr("Latest progress note")}</p><p className="mt-1 text-xs leading-5 text-slate-600">{item.latest_progress_note}</p></div>}</div><div className="shrink-0"><p className="mb-1 text-[10px] font-semibold text-slate-500">{tr("Uploaded image")}</p><ComplaintImage complaint={item} token={token} /></div></div>
          <div className="mt-2"><ComplaintInsights complaint={item} token={token} /></div>
          <div className="mt-3">
            <button type="button" onClick={() => toggleHistory(item)} className="inline-flex items-center gap-1.5 text-xs font-semibold text-brand hover:text-brand-dark">{openHistory[item.id] ? 'Hide status history' : 'View status history'} <Clock3 size={14} /></button>
            {openHistory[item.id] && <div className="mt-2 rounded-xl bg-slate-50 p-3">
              {historyLoading === item.id && <p className="text-xs text-slate-500">{tr("Loading status history…")}</p>}
              {historyError && <p role="alert" className="text-xs text-rose-600">{tr(historyError)}</p>}
              {history[item.id]?.length > 0 && <ol className="space-y-2">{history[item.id].map((entry, index) => <li key={`${entry.changed_at}-${index}`} className="text-xs text-slate-600"><span className="font-semibold">{tr(entry.new_status)}</span>{entry.old_status && ` (${tr('from')} ${tr(entry.old_status)})`} · {displayDate(entry.changed_at)} · {entry.changed_by}{entry.note && <p className="mt-0.5 text-slate-500">{entry.note}</p>}</li>)}</ol>}
              {history[item.id]?.length === 0 && <p className="text-xs text-slate-500">{tr("No status changes recorded.")}</p>}
            </div>}
          </div>
          <div className="mt-4 grid gap-2 sm:grid-cols-[1fr_auto_auto]">
            <textarea value={notes[item.id] || ''} onChange={(event) => setNotes((current) => ({ ...current, [item.id]: event.target.value }))} maxLength={1000} rows={2} placeholder={tr("Record a progress note…")} className="w-full rounded-xl border border-slate-200 px-3 py-2 text-xs outline-none focus:border-brand" aria-label={`Progress note for ${item.id}`} />
            <button type="button" disabled={busy === item.id || !(notes[item.id] || '').trim()} onClick={() => perform(item, { note: notes[item.id].trim() })} className="rounded-xl border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 disabled:opacity-50">{tr("Add note")}</button>
            {nextAction && <button type="button" disabled={busy === item.id} onClick={() => perform(item, { action: nextAction.action, ...((notes[item.id] || '').trim() ? { note: notes[item.id].trim() } : {}) })} className="rounded-xl bg-brand px-3 py-2 text-xs font-bold text-white disabled:opacity-50">{busy === item.id ? 'Saving…' : nextAction.label}</button>}
          </div>
          {!['Completed', 'Resolved'].includes(item.status) && <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3"><label htmlFor={`eta-${item.id}`} className="text-[10px] font-semibold text-slate-500">{tr("Estimated completion")}</label><input id={`eta-${item.id}`} type="datetime-local" value={etaValues[item.id] ?? toLocalDateTime(item.expected_completion_at)} onChange={(event) => setEtaValues((current) => ({ ...current, [item.id]: event.target.value }))} className="rounded-lg border border-slate-200 px-2 py-1.5 text-[10px]" /><button type="button" disabled={busy === item.id || !(etaValues[item.id] ?? toLocalDateTime(item.expected_completion_at))} onClick={() => perform(item, { expected_completion_at: new Date(etaValues[item.id] ?? toLocalDateTime(item.expected_completion_at)).toISOString() })} className="rounded-lg border border-slate-200 px-3 py-1.5 text-[10px] font-semibold text-slate-700 disabled:opacity-50">{tr("Save ETA")}</button><span className="text-[9px] text-slate-400">{tr("Estimate only; citizens will see the update.")}</span></div>}
        </article>
      })}</div> : <p className="py-8 text-center text-sm text-slate-500">{tr("No complaints are currently assigned to this department.")}</p>}
    </Panel>
  </>
}

function DepartmentOverview({ complaints }) {
  const colors = ['#2463eb', '#43b89c', '#f5a623', '#8b70e8', '#ef7891', '#56a7bb']
  const values = departments.map((name, index) => {
    const assigned = complaints.filter((item) => item.department === name)
    const resolved = assigned.filter((item) => ['Resolved', 'Completed'].includes(item.status)).length
    return { name, total: assigned.length, rate: assigned.length ? Math.round((resolved / assigned.length) * 100) : 0, color: colors[index % colors.length] }
  })
  return <><PageHeading eyebrow="Municipal dashboard" title={tr("Departments")} description="A snapshot of work across municipal teams." /><div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{values.map((item) => <div key={item.name} className="rounded-2xl border border-slate-100 bg-white p-5 shadow-card"><div className="flex items-start justify-between"><span className="grid h-10 w-10 place-items-center rounded-xl bg-slate-50" style={{ color: item.color }}><Users size={19} /></span><span className="rounded-full bg-emerald-50 px-2.5 py-1 text-[10px] font-bold text-emerald-700">{item.rate}{tr("% resolved")}</span></div><h2 className="mt-4 text-sm font-bold text-ink">{item.name}</h2><p className="mt-1 text-xs text-slate-500">{item.total} {tr("complaints assigned")}</p><div className="mt-4 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full" style={{ width: `${item.rate}%`, backgroundColor: item.color }} /></div><p className="mt-2 text-[10px] text-slate-400">{tr("Resolution rate · Live API records")}</p></div>)}</div></>
}

function AdminDashboard({ complaints, assignDepartment, updatePriority, token, summary, citizens, loading }) {
  return <Routes><Route index element={<AdminOverview complaints={complaints} assignDepartment={assignDepartment} updatePriority={updatePriority} token={token} summary={summary} />} /><Route path="complaints" element={<MunicipalComplaints complaints={complaints} assignDepartment={assignDepartment} updatePriority={updatePriority} admin token={token} loading={loading} />} /><Route path="citizens" element={<CitizenOverviewAdmin complaints={complaints} summary={summary} citizens={citizens} loading={loading} />} /><Route path="*" element={<AdminOverview complaints={complaints} assignDepartment={assignDepartment} updatePriority={updatePriority} token={token} summary={summary} />} /></Routes>
}

function AdminOverview({ complaints, assignDepartment, updatePriority, token, summary }) {
  const pending = complaints.filter((item) => ['Pending', 'Accepted'].includes(item.status)).length
  const resolved = complaints.filter((item) => ['Resolved', 'Completed'].includes(item.status)).length
  const resolutionRate = summary?.resolution_rate ?? (complaints.length ? Math.round((resolved / complaints.length) * 100) : 0)
  const overdue = summary?.overdue ?? complaints.filter((item) => item.overdue && item.status !== 'Resolved').length
  const needsReview = summary?.needs_review ?? complaints.filter((item) => item.assignment_review_required).length
  const departmentCounts = new Map((summary?.by_department || []).map((item) => [item.name, item.count]))
  const departmentPerformance = departments.map((name, index) => {
    const assigned = complaints.filter((item) => item.department === name)
    const resolvedCount = assigned.filter((item) => ['Resolved', 'Completed'].includes(item.status)).length
    return {
      name,
      rate: assigned.length ? Math.round((resolvedCount / assigned.length) * 100) : 0,
      count: departmentCounts.get(name) ?? assigned.length,
      color: ['#2463eb', '#43b89c', '#f5a623', '#8b70e8', '#ef7891', '#56a7bb'][index % 6],
    }
  })
  return <><PageHeading eyebrow="Admin dashboard" title={tr("Citywide overview")} description="A high-level view of civic services and community impact." action={<button className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-xs font-semibold text-slate-600"><span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> {tr("Riverdale")} <ChevronDown size={14} /></button>} />
    <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-5"><StatCard icon={FileText} label="Total complaints" value={summary?.total ?? complaints.length} footnote="Authenticated database records" /><StatCard icon={Clock3} label="Pending complaints" value={summary?.pending ?? pending} tint="amber" /><StatCard icon={Activity} label="In progress" value={summary?.in_progress ?? complaints.filter((item) => item.status === 'In progress').length} tint="violet" /><StatCard icon={CheckCircle2} label="Completed complaints" value={summary?.completed ?? resolved} tint="green" /><StatCard icon={CircleHelp} label="Needs assignment review" value={needsReview} tint="amber" /></div>
    <div className="mb-5 grid gap-5 xl:grid-cols-[1.4fr_.8fr]"><Panel title={tr("Municipal performance")} subtitle="Monthly issues received and resolved · Last six months"><ResponsiveContainer width="100%" height={270}><BarChart data={summary?.monthly || []} barGap={7} margin={{ top: 5, right: 2, left: -22, bottom: 0 }}><CartesianGrid stroke="#eef2f7" vertical={false} /><XAxis dataKey="month" axisLine={false} tickLine={false} tick={{ fill: '#8b98aa', fontSize: 11 }} dy={8} /><YAxis axisLine={false} tickLine={false} tick={{ fill: '#8b98aa', fontSize: 10 }} /><Tooltip contentStyle={{ borderRadius: 12, border: '1px solid #e9eef5', fontSize: 12 }} /><Bar dataKey="received" name="Received" fill="#cbdcf9" radius={[5, 5, 0, 0]} /><Bar dataKey="resolved" name="Resolved" fill="#2463eb" radius={[5, 5, 0, 0]} /></BarChart></ResponsiveContainer><div className="mt-1 flex justify-center gap-5 text-[10px] text-slate-500"><span><i className="mr-1.5 inline-block h-2 w-2 rounded-sm bg-blue-200" />{tr("Received")}</span><span><i className="mr-1.5 inline-block h-2 w-2 rounded-sm bg-brand" />{tr("Resolved")}</span></div></Panel>
      <Panel title={tr("Service health")} subtitle="Resolution rates at a glance"><div className="flex items-center justify-center py-3"><div className="relative grid h-40 w-40 place-items-center rounded-full" style={{ background: `conic-gradient(#43b89c 0% ${resolutionRate}%, #e9eef5 ${resolutionRate}% 100%)` }}><div className="grid h-[122px] w-[122px] content-center justify-items-center rounded-full bg-white"><p className="font-display text-3xl font-extrabold text-ink">{resolutionRate}%</p><p className="text-[10px] text-slate-400">{tr("Resolved")}</p></div></div></div><div className="space-y-3 border-t border-slate-100 pt-4"><HealthLine label="Resolution rate" value={`${resolutionRate}%`} good /><HealthLine label="Overdue reports" value={overdue} warning /><p className="text-[10px] leading-4 text-slate-400">{tr("Overdue flag and response-time/community satisfaction figures are illustrative sample data.")}</p></div></Panel></div>
    <div className="mb-5 grid gap-5 xl:grid-cols-[1.3fr_.7fr]"><Panel title={tr("Department performance")} subtitle="Resolution rate and assigned volume · Shared complaint records"><div className="space-y-4">{departmentPerformance.map((item) => <div key={item.name}><div className="mb-1.5 flex justify-between text-xs"><span className="font-semibold text-slate-700">{item.name}</span><span className="text-slate-500">{item.rate}% <span className="text-slate-400">· {item.count} {tr("reports")}</span></span></div><div className="h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full" style={{ width: `${item.rate}%`, backgroundColor: item.color }} /></div></div>)}</div></Panel>
      <Panel title={tr("Community overview")} subtitle="Registered users across Riverdale"><div className="flex items-center gap-4"><span className="grid h-12 w-12 place-items-center rounded-2xl bg-blue-50 text-brand"><Users size={23} /></span><div><p className="font-display text-2xl font-extrabold text-ink">{summary?.citizen_count ?? 0}</p><p className="text-xs text-slate-500">{tr("Registered citizens")}</p></div></div><div className="mt-5 space-y-3 border-t border-slate-100 pt-4"><HealthLine label="Municipal departments" value={departments.length} /><HealthLine label="Resolution rate" value={`${resolutionRate}%`} good /><HealthLine label="Overdue reports" value={overdue} warning /></div><Link to="/admin/citizens" className="mt-4 block text-xs font-bold text-brand">{tr("View citizen overview")} <ArrowRight size={13} className="ml-1 inline" /></Link></Panel></div>
    <Panel title={tr("Priority complaints")} subtitle="Monitor reports and coordinate department assignment" action={<Link to="/admin/complaints" className="text-xs font-bold text-brand">{tr("View all")} <ArrowRight size={13} className="ml-1 inline" /></Link>}>{complaints.length ? <ComplaintTable complaints={complaints.slice(0, 3)} token={token} showCitizen onAssign={assignDepartment} onPriorityChange={updatePriority} /> : <p className="py-8 text-center text-sm text-slate-500">{tr("No complaints have been submitted yet.")}</p>}</Panel>
    <div className="mt-5 grid gap-5 xl:grid-cols-2"><CategoryMappingPanel token={token} /><AdminModelMonitor token={token} /><MunicipalAnalyticsPanel token={token} /><AdminDeliveryMonitor token={token} /></div>
  </>
}

function HealthLine({ label, value, good, warning }) { return <div className="flex items-center justify-between text-xs"><span className="text-slate-500">{tr(label)}</span><span className={cx('font-bold', good ? 'text-emerald-600' : warning ? 'text-rose-600' : 'text-ink')}>{value}</span></div> }

function CitizenOverviewAdmin({ complaints, summary, citizens, loading }) {
  const rows = [['Registered citizens', summary?.citizen_count ?? 0, 'Authenticated citizen accounts'], ['Municipal departments', departments.length, 'Configured service departments'], ['Reports submitted', complaints.length, 'Shared complaint records'], ['Resolution rate', `${summary?.resolution_rate ?? 0}%`, 'Based on current complaint records']]
  return <><PageHeading eyebrow="Admin dashboard" title={tr("Citizens & community")} description="Registered accounts and complaint progress from the SQLite database." /><div className="mb-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{rows.map(([label, value, detail]) => <div key={label} className="rounded-2xl border border-slate-100 bg-white p-5 shadow-card"><p className="text-xs font-semibold text-slate-500">{label}</p><p className="mt-3 font-display text-2xl font-extrabold text-ink">{value}</p><p className="mt-1 text-[10px] text-slate-500">{detail}</p></div>)}</div>  <Panel title={tr("Citizen complaint progress")} subtitle={tr('{{count}} registered accounts · Restricted to administrators', { count: citizens.length })}>{loading ? <p className="py-8 text-center text-sm text-slate-400">{tr("Loading citizen progress…")}</p> : citizens.length ? <div className="scrollbar-hidden -mx-5 overflow-x-auto sm:mx-0"><table className="w-full min-w-[700px] text-left"><thead><tr className="border-y border-slate-100 bg-slate-50/70 text-[10px] font-bold uppercase tracking-[.1em] text-slate-400"><th className="px-5 py-3">{tr("Citizen")}</th><th className="px-4 py-3">{tr("Registered")}</th><th className="px-4 py-3">{tr("Complaints")}</th><th className="px-4 py-3">{tr("Pending")}</th><th className="px-4 py-3">{tr("Resolved")}</th><th className="px-4 py-3">{tr("Resolution rate")}</th></tr></thead><tbody>{citizens.map((citizen) => <tr key={citizen.id} className="border-b border-slate-50 last:border-0"><td className="px-5 py-3.5"><p className="text-xs font-semibold text-ink">{citizen.name}</p><p className="mt-1 text-[10px] text-slate-400">{citizen.email}</p></td><td className="px-4 py-3.5  text-[11px] text-slate-500">{displayDate(citizen.created_at)}</td><td className="px-4 py-3.5 text-xs text-slate-600">{citizen.complaint_count}</td><td className="px-4 py-3.5 text-xs text-amber-700">{citizen.pending_count}</td><td className="px-4 py-3.5 text-xs text-emerald-700">{citizen.resolved_count}</td><td className="px-4 py-3.5 text-xs font-semibold text-ink">{citizen.resolution_rate}%</td></tr>)}</tbody></table></div> : <p className="py-8 text-center text-sm text-slate-500">{tr("No citizen accounts have registered yet.")}</p>}</Panel></>
}

function ProtectedRoute({ role, session, children }) {
  if (session?.user?.role !== role || !session?.token) {
    const loginPath = { citizen: '/citizen/login', municipal: '/officer/login', department: '/department/login', admin: '/admin/login' }[role]
    return <Navigate to={loginPath} replace />
  }
  return children
}

function App() {
  useTranslation()
  const location = useLocation()
  const [session, setSession] = useState(null)
  const [complaints, setComplaints] = useState([])
  const [summary, setSummary] = useState(null)
  const [citizens, setCitizens] = useState([])
  const [loading, setLoading] = useState(false)
  const [apiError, setApiError] = useState('')

  useEffect(() => {
    if (!session?.token) {
      setComplaints([])
      setSummary(null)
      setCitizens([])
      setLoading(false)
      return undefined
    }
    let active = true
    const refresh = async (initial = false) => {
      if (initial) setLoading(true)
      try {
        const [list, stats, citizenResult] = await Promise.all([
          api.listComplaints(session.token, session.user.role),
          api.getSummary(session.token),
          session.user.role === 'admin' ? api.listCitizens(session.token) : Promise.resolve({ citizens: [] }),
        ])
        if (!active) return
        setComplaints(list.complaints)
        setSummary(stats)
        setCitizens(citizenResult.citizens)
        setApiError('')
      } catch (error) {
        if (active) setApiError(error.message)
      } finally {
        if (active && initial) setLoading(false)
      }
    }
    refresh(true)
    const interval = window.setInterval(() => refresh(false), 5000)
    return () => {
      active = false
      window.clearInterval(interval)
    }
  }, [session, location.pathname])

  const addComplaint = async (details) => {
    try {
      const entry = await api.submitComplaint(session.token, details)
      setComplaints((current) => [entry, ...current])
      setSummary((current) => current ? {
        ...current,
        total: current.total + 1,
        pending: current.pending + 1,
      } : current)
      setApiError('')
      return entry
    } catch (error) {
      setApiError(error.message)
      throw error
    }
  }

  const updateComplaint = async (id, updates) => {
    try {
      const updated = await api.updateComplaint(session.token, id, updates)
      setComplaints((current) => current.map((item) => item.id === id ? updated : item))
      setApiError('')
      return updated
    } catch (error) {
      setApiError(error.message)
    }
  }

  const updateDepartmentComplaint = async (id, updates) => {
    try {
      const updated = await api.updateDepartmentComplaint(session.token, id, updates)
      setComplaints((current) => current.map((item) => item.id === id ? updated : item))
      setApiError('')
      return updated
    } catch (error) {
      setApiError(error.message)
      return undefined
    }
  }

  const assignDepartment = async (id, department) => {
    return updateComplaint(id, { department })
  }

  const updatePriority = async (id, priority) => {
    return updateComplaint(id, { priority })
  }

  const importLegacy = async (entries) => {
    if (!entries.length) throw new Error('There are no legacy complaints to import.')
    const result = await api.importLegacyComplaints(session.token, entries)
    try {
      const [list, stats] = await Promise.all([
        api.listComplaints(session.token, 'citizen'),
        api.getSummary(session.token),
      ])
      setComplaints(list.complaints)
      setSummary(stats)
      setApiError('')
    } catch (error) {
      setApiError(`Backup import completed, but the dashboard refresh failed: ${error.message}`)
    }
    return result
  }

  const signOut = () => setSession(null)
  return <Routes>
    <Route path="/" element={<Landing />} />
    <Route path="/citizen/login" element={<AuthPage type="login" onAuthenticated={setSession} />} />
    <Route path="/citizen/register" element={<AuthPage type="register" onAuthenticated={setSession} />} />
    <Route path="/officer/login" element={<AuthPage type="officer" onAuthenticated={setSession} />} />
    <Route path="/department/login" element={<AuthPage type="department" onAuthenticated={setSession} />} />
    <Route path="/admin/login" element={<AuthPage type="admin" onAuthenticated={setSession} />} />
    <Route path="/citizen/*" element={<ProtectedRoute role="citizen" session={session}><AppShell role="citizen" user={session?.user} token={session?.token} apiError={apiError} loading={loading} onSignOut={signOut}><CitizenDashboard complaints={complaints} addComplaint={addComplaint} token={session?.token} summary={summary} loading={loading} user={session?.user} onImportLegacy={importLegacy} /></AppShell></ProtectedRoute>} />
    <Route path="/municipal/*" element={<ProtectedRoute role="municipal" session={session}><AppShell role="municipal" user={session?.user} token={session?.token} apiError={apiError} loading={loading} onSignOut={signOut}><MunicipalDashboard complaints={complaints} token={session?.token} summary={summary} loading={loading} /></AppShell></ProtectedRoute>} />
    <Route path="/department/*" element={<ProtectedRoute role="department" session={session}><AppShell role="department" user={session?.user} token={session?.token} apiError={apiError} loading={loading} onSignOut={signOut}><DepartmentDashboard complaints={complaints} updateDepartmentComplaint={updateDepartmentComplaint} token={session?.token} loading={loading} user={session?.user} /></AppShell></ProtectedRoute>} />
    <Route path="/admin/*" element={<ProtectedRoute role="admin" session={session}><AppShell role="admin" user={session?.user} token={session?.token} apiError={apiError} loading={loading} onSignOut={signOut}><AdminDashboard complaints={complaints} assignDepartment={(id, department) => updateComplaint(id, { department })} updatePriority={(id, priority) => updateComplaint(id, { priority })} token={session?.token} summary={summary} citizens={citizens} loading={loading} /></AppShell></ProtectedRoute>} />
    <Route path="*" element={<Landing />} />
  </Routes>
}

export default App
