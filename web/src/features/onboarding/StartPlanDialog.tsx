import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'

import { createEmployee, createTemplate, startPlan } from './onboardingApi'
import { useEmployees, useOnboardingTemplates, useStarterTemplate } from './useOnboarding'

const labelClass = 'text-ink-strong text-xs font-medium'

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

function errorFor(status: number, t: (key: string) => string): string {
  if (status === 403) {
    return t('onboarding.errors.forbidden')
  }
  if (status === 404) {
    return t('onboarding.errors.employeeNotFound')
  }
  if (status === 409) {
    return t('onboarding.errors.conflict')
  }
  if (status === 422) {
    return t('onboarding.errors.invalid')
  }
  return t('onboarding.errors.failed')
}

/**
 * Start an onboarding plan: pick an existing hire, or create the hire in the same
 * flow so a solo user never has to leave the workspace. Both paths record a
 * named human; the template is optional (the server picks the engineering
 * default when omitted).
 */
export function StartPlanDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [, setSearchParams] = useSearchParams()
  const employees = useEmployees(open)
  const templates = useOnboardingTemplates(open)
  const starter = useStarterTemplate(open && (templates.data ?? []).length === 0)
  const [mode, setMode] = useState<'existing' | 'new'>('existing')
  const [employeeId, setEmployeeId] = useState('')
  const [fullName, setFullName] = useState('')
  const [hireDate, setHireDate] = useState(today())
  const [email, setEmail] = useState('')
  const [jobTitle, setJobTitle] = useState('')
  const [templateId, setTemplateId] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [seeding, setSeeding] = useState(false)

  const hasTemplates = (templates.data ?? []).length > 0

  async function seedStarterTemplate() {
    const draft = starter.data
    if (draft === null || draft === undefined) {
      return
    }
    setProblem(null)
    setSeeding(true)
    const created = await createTemplate({
      name: draft.name,
      description: draft.description,
      applies_to_contract_types: draft.applies_to_contract_types,
      applies_to_roles: draft.applies_to_roles,
      steps: draft.steps,
    })
    setSeeding(false)
    if (created === null) {
      setProblem(errorFor(422, t))
      return
    }
    setTemplateId(created.id)
    await queryClient.invalidateQueries({ queryKey: ['onboarding', 'templates'] })
  }

  function close(next: boolean) {
    if (!next) {
      setProblem(null)
    }
    onOpenChange(next)
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (mode === 'existing' && employeeId === '') {
      setProblem(t('onboarding.errors.employeeRequired'))
      return
    }
    if (mode === 'new' && fullName.trim() === '') {
      setProblem(t('onboarding.errors.nameRequired'))
      return
    }
    setProblem(null)
    setBusy(true)

    let targetEmployeeId = employeeId
    if (mode === 'new') {
      const created = await createEmployee({
        full_name: fullName.trim(),
        hire_date: hireDate,
        // No actor: the API attributes the employee to the API key holder.
        email: email.trim() === '' ? null : email.trim(),
        job_title: jobTitle.trim() === '' ? null : jobTitle.trim(),
        phone: null,
        org_unit_id: null,
        manager_id: null,
        work_location: null,
        probation_end_date: null,
        employee_number: null,
      })
      if (created === null) {
        setBusy(false)
        setProblem(errorFor(422, t))
        return
      }
      targetEmployeeId = created.id
    }

    const result = await startPlan({
      employee_id: targetEmployeeId,
      template_id: templateId === '' ? null : templateId,
    })
    setBusy(false)

    if (result.status === 201 && result.plan !== undefined) {
      await queryClient.invalidateQueries({ queryKey: ['onboarding'] })
      close(false)
      setSearchParams({ room: 'queue', plan: result.plan.id })
      return
    }
    setProblem(errorFor(result.status, t))
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('onboarding.startDialog.title')}</DialogTitle>
          <DialogDescription>{t('onboarding.startDialog.hint')}</DialogDescription>
        </DialogHeader>

        <form onSubmit={(event) => void handleSubmit(event)} className="flex flex-col gap-4">
          {problem !== null ? (
            <p role="alert" className="text-error flex items-center gap-1 text-xs">
              <span aria-hidden="true">●</span>
              {problem}
            </p>
          ) : null}

          <div className="flex flex-col gap-1.5">
            <span className="text-ink-strong text-xs font-medium">
              {t('onboarding.startDialog.hireSource')}
            </span>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                size="xs"
                variant={mode === 'existing' ? 'default' : 'outline'}
                onClick={() => setMode('existing')}
              >
                {t('onboarding.startDialog.existingHire')}
              </Button>
              <Button
                type="button"
                size="xs"
                variant={mode === 'new' ? 'default' : 'outline'}
                onClick={() => setMode('new')}
              >
                {t('onboarding.startDialog.newHire')}
              </Button>
            </div>
          </div>

          {mode === 'existing' ? (
            <div className="flex flex-col gap-1.5">
              <label htmlFor="onboarding-employee" className={labelClass}>
                {t('onboarding.startDialog.employee')}
              </label>
              <select
                id="onboarding-employee"
                value={employeeId}
                onChange={(event) => setEmployeeId(event.target.value)}
                className="border-line bg-surface text-ink h-9 rounded-md border px-2 text-sm"
              >
                <option value="">{t('onboarding.startDialog.employeePlaceholder')}</option>
                {(employees.data ?? []).map((employee) => (
                  <option key={employee.id} value={employee.id}>
                    {employee.full_name}
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="onboarding-name" className={labelClass}>
                  {t('onboarding.startDialog.fullName')}
                </label>
                <Input
                  id="onboarding-name"
                  value={fullName}
                  onChange={(event) => setFullName(event.target.value)}
                  autoComplete="off"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="onboarding-hire-date" className={labelClass}>
                  {t('onboarding.startDialog.hireDate')}
                </label>
                <Input
                  id="onboarding-hire-date"
                  type="date"
                  value={hireDate}
                  onChange={(event) => setHireDate(event.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="onboarding-email" className={labelClass}>
                  {t('onboarding.startDialog.email')}
                </label>
                <Input
                  id="onboarding-email"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  autoComplete="off"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="onboarding-job-title" className={labelClass}>
                  {t('onboarding.startDialog.jobTitle')}
                </label>
                <Input
                  id="onboarding-job-title"
                  value={jobTitle}
                  onChange={(event) => setJobTitle(event.target.value)}
                  autoComplete="off"
                />
              </div>
            </>
          )}

          <div className="flex flex-col gap-1.5">
            <label htmlFor="onboarding-template" className="text-ink-strong text-xs font-medium">
              {t('onboarding.startDialog.template')}
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <select
                id="onboarding-template"
                value={templateId}
                onChange={(event) => setTemplateId(event.target.value)}
                className="border-line bg-surface text-ink h-9 rounded-md border px-2 text-sm"
              >
                <option value="">
                  {hasTemplates
                    ? t('onboarding.startDialog.templatePlaceholder')
                    : t('onboarding.startDialog.templateDefault')}
                </option>
                {(templates.data ?? []).map((template) => (
                  <option key={template.id} value={template.id}>
                    {template.name}
                  </option>
                ))}
              </select>
              {hasTemplates ? (
                <Badge variant="outline" className="text-2xs">
                  {t('onboarding.templatesAvailable', { count: (templates.data ?? []).length })}
                </Badge>
              ) : starter.data !== null && starter.data !== undefined ? (
                <Button
                  type="button"
                  size="xs"
                  variant="outline"
                  disabled={seeding}
                  onClick={() => void seedStarterTemplate()}
                >
                  {t('onboarding.startDialog.createStarter')}
                </Button>
              ) : null}
            </div>
            {hasTemplates ? null : (
              <span className="text-2xs text-ink-muted">
                {t('onboarding.startDialog.noTemplates')}
              </span>
            )}
          </div>

          <DialogFooter>
            <Button type="submit" size="sm" disabled={busy}>
              {t('onboarding.startDialog.confirm')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
