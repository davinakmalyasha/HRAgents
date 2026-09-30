import { useQueryClient } from '@tanstack/react-query'
import { ChevronsUpDown } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

import { createOffer, reviseOffer } from './offerApi'
import type { OfferTerms, OfferView } from './offer'

const EMPLOYMENT_TYPES = ['pkwtt', 'pkwt', 'internship', 'freelance'] as const
type EmploymentType = (typeof EMPLOYMENT_TYPES)[number]

const fieldClass = 'flex flex-col gap-1.5'
const labelClass = 'text-xs font-medium text-ink-strong'

function dateInput(value: string | null | undefined): string {
  return value === null || value === undefined ? '' : value.slice(0, 10)
}

/**
 * Create or revise offer terms. Terms are human-entered (the system never
 * invents an offer); revisions are append-only on the server, and nothing
 * reaches the candidate until the offer message is queued.
 */
export function OfferFormDialog({
  applicationId,
  offer,
  open,
  onOpenChange,
}: {
  applicationId: string
  offer: OfferView | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [position, setPosition] = useState(offer?.terms.position_title ?? '')
  const [employmentType, setEmploymentType] = useState<EmploymentType>(
    (offer?.terms.employment_type as EmploymentType | undefined) ?? 'pkwtt',
  )
  const [startDate, setStartDate] = useState(dateInput(offer?.terms.start_date))
  const [endDate, setEndDate] = useState(dateInput(offer?.terms.end_date))
  const [probation, setProbation] = useState(
    offer?.terms.probation_months == null ? '' : String(offer.terms.probation_months),
  )
  const [salary, setSalary] = useState(offer == null ? '' : String(offer.terms.salary_amount))
  const [currency, setCurrency] = useState(offer?.terms.salary_currency ?? 'IDR')
  const [notes, setNotes] = useState(offer?.terms.notes ?? '')
  const [expires, setExpires] = useState(dateInput(offer?.terms.expires_at))
  const [note, setNote] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  function close(next: boolean) {
    if (!next) {
      setProblem(null)
    }
    onOpenChange(next)
  }

  function validate(): string[] {
    const problems: string[] = []
    if (position.trim() === '') {
      problems.push(t('offer.errors.positionRequired'))
    }
    if (startDate === '') {
      problems.push(t('offer.errors.startRequired'))
    }
    const amount = Number(salary)
    if (salary.trim() === '' || !Number.isFinite(amount) || amount < 0) {
      problems.push(t('offer.errors.salaryInvalid'))
    }
    if (endDate !== '' && startDate !== '' && endDate <= startDate) {
      problems.push(t('offer.errors.endBeforeStart'))
    }
    if (employmentType === 'pkwt' && endDate === '') {
      problems.push(t('offer.errors.pkwtNeedsEnd'))
    }
    if (probation.trim() !== '') {
      const months = Number(probation)
      if (!Number.isInteger(months) || months < 0 || months > 12) {
        problems.push(t('offer.errors.probationInvalid'))
      }
    }
    return problems
  }

  function errorFor(status: number, detail?: string): string {
    if (status === 409) {
      if (detail?.includes('draft')) {
        return t('offer.errors.draftOnly')
      }
      return t('offer.errors.conflict')
    }
    if (status === 403) {
      return t('offer.errors.forbidden')
    }
    if (status === 404) {
      return t('offer.errors.notFound')
    }
    return t('offer.errors.failed')
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const problems = validate()
    if (problems.length > 0) {
      setProblem(problems[0] ?? null)
      return
    }
    setProblem(null)
    setBusy(true)
    const terms: OfferTerms = {
      position_title: position.trim(),
      employment_type: employmentType,
      start_date: startDate,
      end_date: endDate === '' ? null : endDate,
      probation_months: probation.trim() === '' ? null : Number(probation),
      salary_amount: Number(salary),
      salary_currency: currency.trim() === '' ? 'IDR' : currency.trim().toUpperCase(),
      notes: notes.trim(),
      expires_at: expires === '' ? null : `${expires}T23:59:59Z`,
    }
    const result =
      offer === null
        ? await createOffer({
            application_id: applicationId,
            terms,
            note: '',
          })
        : await reviseOffer(offer.id, { terms, note: note.trim() })
    setBusy(false)
    if (result.status === 200 || result.status === 201) {
      await queryClient.invalidateQueries({ queryKey: ['offers', applicationId] })
      close(false)
      return
    }
    setProblem(errorFor(result.status, result.detail))
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {offer === null ? t('offer.form.createTitle') : t('offer.form.reviseTitle')}
          </DialogTitle>
          <DialogDescription>{t('offer.form.hint')}</DialogDescription>
        </DialogHeader>

        <form onSubmit={(event) => void handleSubmit(event)} className="flex flex-col gap-4">
          {problem !== null ? (
            <p role="alert" className="text-error flex items-center gap-1 text-xs">
              <span aria-hidden="true">●</span>
              {problem}
            </p>
          ) : null}

          <div className={fieldClass}>
            <label htmlFor="offer-position" className={labelClass}>
              {t('offer.terms.position')}
            </label>
            <Input
              id="offer-position"
              value={position}
              onChange={(event) => setPosition(event.target.value)}
              placeholder={t('offer.form.positionPlaceholder')}
              autoComplete="off"
            />
          </div>

          <div className={fieldClass}>
            <span id="offer-type-label" className={labelClass}>
              {t('offer.terms.type')}
            </span>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  aria-labelledby="offer-type-label"
                  className="justify-between"
                >
                  <span>{t(`offer.types.${employmentType}`)}</span>
                  <ChevronsUpDown aria-hidden="true" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                <DropdownMenuRadioGroup
                  value={employmentType}
                  onValueChange={(value) => setEmploymentType(value as EmploymentType)}
                >
                  {EMPLOYMENT_TYPES.map((option) => (
                    <DropdownMenuRadioItem key={option} value={option}>
                      {t(`offer.types.${option}`)}
                    </DropdownMenuRadioItem>
                  ))}
                </DropdownMenuRadioGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className={fieldClass}>
              <label htmlFor="offer-start" className={labelClass}>
                {t('offer.terms.start')}
              </label>
              <Input
                id="offer-start"
                type="date"
                value={startDate}
                onChange={(event) => setStartDate(event.target.value)}
              />
            </div>
            <div className={fieldClass}>
              <label htmlFor="offer-end" className={labelClass}>
                {t('offer.terms.end')}
              </label>
              <Input
                id="offer-end"
                type="date"
                value={endDate}
                onChange={(event) => setEndDate(event.target.value)}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className={fieldClass}>
              <label htmlFor="offer-salary" className={labelClass}>
                {t('offer.form.salary')}
              </label>
              <Input
                id="offer-salary"
                type="number"
                min="0"
                value={salary}
                onChange={(event) => setSalary(event.target.value)}
                className="font-mono text-xs"
              />
            </div>
            <div className={fieldClass}>
              <label htmlFor="offer-currency" className={labelClass}>
                {t('offer.form.currency')}
              </label>
              <Input
                id="offer-currency"
                value={currency}
                onChange={(event) => setCurrency(event.target.value)}
                className="font-mono text-xs"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className={fieldClass}>
              <label htmlFor="offer-probation" className={labelClass}>
                {t('offer.form.probation')}
              </label>
              <Input
                id="offer-probation"
                type="number"
                min="0"
                max="12"
                value={probation}
                onChange={(event) => setProbation(event.target.value)}
                className="font-mono text-xs"
              />
            </div>
            <div className={fieldClass}>
              <label htmlFor="offer-expires" className={labelClass}>
                {t('offer.form.expires')}
              </label>
              <Input
                id="offer-expires"
                type="date"
                value={expires}
                onChange={(event) => setExpires(event.target.value)}
              />
            </div>
          </div>

          <div className={fieldClass}>
            <label htmlFor="offer-notes" className={labelClass}>
              {t('offer.terms.notes')}
            </label>
            <Textarea
              id="offer-notes"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              rows={2}
              className="min-h-9"
            />
          </div>

          {offer === null ? null : (
            <div className={fieldClass}>
              <label htmlFor="offer-note" className={labelClass}>
                {t('offer.form.note')}
              </label>
              <Input
                id="offer-note"
                value={note}
                onChange={(event) => setNote(event.target.value)}
                autoComplete="off"
              />
            </div>
          )}

          <DialogFooter>
            <Button type="submit" size="sm" disabled={busy}>
              {offer === null ? t('offer.form.save') : t('offer.form.update')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
