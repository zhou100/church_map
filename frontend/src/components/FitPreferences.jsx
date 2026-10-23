import { useEffect, useId, useRef, useState } from 'react'
import Icon from './Icon'
import {
  EMPTY_PREFERENCES,
  WORSHIP_STYLES,
  hasPreferences,
  preferencePhrase,
  preferenceSummary,
} from '../preferences'

// "Make these fit you": three questions, all optional. Inline under the
// entry on desktop; a native <dialog> bottom sheet at phone width, which
// brings focus trapping, Esc and an inert page with it. Controlled: the page
// owns `prefs` and saves them. Plan: docs/plans/landing_fit_preferences_plan.md.

const PHONE = '(max-width: 760px)'

function toggle(list, value) {
  return list.includes(value) ? list.filter(item => item !== value) : [...list, value]
}

function Chip({ active, onClick, children }) {
  return (
    <button
      type="button"
      className={`tag-filter-pill fit-chip${active ? ' tag-active' : ''}`}
      aria-pressed={active}
      onClick={onClick}
    >
      {children}
    </button>
  )
}

function ChipGroup({ question, children }) {
  const id = useId()
  return (
    <div className="fit-group" role="group" aria-labelledby={id}>
      <p className="fit-question" id={id}>{question}</p>
      <div className="fit-chips">{children}</div>
    </div>
  )
}

function Questions({ prefs, languageChips, onChange }) {
  const languageActive = language => prefs.languages.some(l => l.toLowerCase() === language.toLowerCase())
  return (
    <>
      <ChipGroup question="Services in">
        {languageChips.map(language => (
          <Chip
            key={language}
            active={languageActive(language)}
            onClick={() => onChange({
              ...prefs,
              languages: languageActive(language)
                ? prefs.languages.filter(l => l.toLowerCase() !== language.toLowerCase())
                : [...prefs.languages, language],
            })}
          >
            {language}
          </Chip>
        ))}
      </ChipGroup>
      <ChipGroup question="Sunday feels like">
        {WORSHIP_STYLES.map(style => (
          <Chip
            key={style.value}
            active={prefs.worship.includes(style.value)}
            onClick={() => onChange({ ...prefs, worship: toggle(prefs.worship, style.value) })}
          >
            {style.label}
          </Chip>
        ))}
      </ChipGroup>
      <ChipGroup question="Kids">
        <Chip active={prefs.kids} onClick={() => onChange({ ...prefs, kids: !prefs.kids })}>
          We&apos;re bringing kids
        </Chip>
      </ChipGroup>
    </>
  )
}

export default function FitPreferences({ prefs, onChange, languageChips, sheetAction, className = '' }) {
  const [open, setOpen] = useState(false)
  const [announcement, setAnnouncement] = useState('')
  const panelId = useId()
  const opener = useRef(null)
  const dialog = useRef(null)
  const panel = useRef(null)
  const active = hasPreferences(prefs)

  function change(next) {
    onChange(next)
    setAnnouncement(hasPreferences(next)
      ? `Showing churches with ${preferencePhrase(next, 'and')} first.`
      : 'Preferences cleared.')
  }

  function focusFirstChip() {
    requestAnimationFrame(() => panel.current?.querySelector('.fit-chip')?.focus())
  }

  function handleOpen() {
    const sheet = dialog.current
    const phone = typeof window.matchMedia === 'function' && window.matchMedia(PHONE).matches
    if (phone && typeof sheet?.showModal === 'function') {
      sheet.showModal()
      return
    }
    if (open) {
      setOpen(false)
      return
    }
    setOpen(true)
    focusFirstChip()
  }

  function closeInline() {
    setOpen(false)
    opener.current?.focus()
  }

  function closeSheet() {
    dialog.current?.close()
  }

  useEffect(() => {
    const sheet = dialog.current
    if (!sheet) return undefined
    const restoreFocus = () => opener.current?.focus()
    sheet.addEventListener('close', restoreFocus)
    return () => sheet.removeEventListener('close', restoreFocus)
  }, [])

  const questions = <Questions prefs={prefs} languageChips={languageChips} onChange={change} />

  return (
    <div className={`fit-preferences ${className}`}>
      {active ? (
        <p className="fit-summary">
          <span>For you:</span> <strong>{preferenceSummary(prefs)}</strong>
          <button
            type="button"
            ref={opener}
            className="fit-edit"
            aria-expanded={open}
            aria-controls={panelId}
            onClick={handleOpen}
          >
            Edit
          </button>
        </p>
      ) : (
        <button
          type="button"
          ref={opener}
          className="fit-entry"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={handleOpen}
        >
          Make these fit you
          <span className="fit-entry-hint">language, worship, kids</span>
          <Icon name="arrow" size={13} />
        </button>
      )}

      {open && (
        <div
          className="fit-panel"
          id={panelId}
          ref={panel}
          onKeyDown={event => event.key === 'Escape' && closeInline()}
        >
          {questions}
          <div className="fit-actions">
            <button type="button" className="fit-done" onClick={closeInline}>Done</button>
            {active && (
              <button type="button" className="fit-clear" onClick={() => change(EMPTY_PREFERENCES)}>Clear</button>
            )}
          </div>
        </div>
      )}

      <dialog ref={dialog} className="fit-sheet" aria-labelledby={`${panelId}-title`}>
        <div className="fit-sheet-head">
          <h2 id={`${panelId}-title`}>What matters to you?</h2>
          <button type="button" className="fit-sheet-close" aria-label="Close" onClick={closeSheet}>
            <span aria-hidden="true">×</span>
          </button>
        </div>
        <div className="fit-sheet-body">{questions}</div>
        <div className="fit-sheet-foot">
          <button
            type="button"
            className="fit-sheet-primary"
            onClick={() => { closeSheet(); sheetAction?.onClick?.() }}
          >
            {sheetAction?.label ?? 'Done'}
          </button>
          {active && (
            <button type="button" className="fit-clear" onClick={() => change(EMPTY_PREFERENCES)}>Clear</button>
          )}
        </div>
      </dialog>

      <p className="sr-only" aria-live="polite">{announcement}</p>
    </div>
  )
}
