import type { StorybookConfig } from '@storybook/react-vite'

const config: StorybookConfig = {
  stories: ['../src/**/*.stories.@(ts|tsx)'],
  addons: [],
  framework: {
    name: '@storybook/react-vite',
    options: {},
  },
  /**
   * The app's Vite config installs the PWA plugin, whose service-worker
   * generation expects the app's entry and output. The component catalog does
   * not need a service worker, so drop it rather than special-casing the build.
   */
  viteFinal: async (viteConfig) => {
    viteConfig.plugins = viteConfig.plugins?.filter((plugin) => {
      const name = (plugin as { name?: string } | null)?.name
      // The app's PWA plugin reaches Storybook without a name; keep only the
      // named plugins (Storybook's own are all named) and drop PWA if named.
      return Boolean(name) && !name.startsWith('vite-plugin-pwa')
    })
    return viteConfig
  },
}

export default config
