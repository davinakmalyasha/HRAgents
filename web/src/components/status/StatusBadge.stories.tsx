import type { Meta, StoryObj } from '@storybook/react-vite'

import { StatusBadge } from './StatusBadge'

const meta = {
  title: 'Status/StatusBadge',
  component: StatusBadge,
  args: { tone: 'waiting', labelKey: 'approvals.escalated' },
} satisfies Meta<typeof StatusBadge>

export default meta
type Story = StoryObj<typeof meta>

export const Waiting: Story = {}

export const Error: Story = {
  args: { tone: 'error', labelKey: 'approvals.raisedByAgent' },
}

export const Done: Story = {
  args: { tone: 'done', labelKey: 'communication.statuses.sent' },
}
