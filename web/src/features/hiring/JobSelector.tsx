import { ChevronsUpDown } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { components } from '@/api/schema'

type JobView = components['schemas']['JobView']

interface JobSelectorProps {
  jobs: JobView[]
  value: string | null
  onChange: (value: string | null) => void
}

export function JobSelector({ jobs, value, onChange }: JobSelectorProps) {
  const { t } = useTranslation()
  const selected = jobs.find((job) => job.id === value)
  const label = selected?.title ?? t('hiring.allJobs')

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" aria-label={t('hiring.job')}>
          <span className="max-w-48 truncate">{label}</span>
          <ChevronsUpDown aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuItem onSelect={() => onChange(null)}>{t('hiring.allJobs')}</DropdownMenuItem>
        {jobs.map((job) => (
          <DropdownMenuItem key={job.id} onSelect={() => onChange(job.id)}>
            <span className="max-w-64 truncate">{job.title}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
