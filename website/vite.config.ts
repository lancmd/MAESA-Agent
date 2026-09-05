import tailwindcss from '@tailwindcss/postcss';
import vinext from 'vinext';
import { defineConfig } from 'vite';

export default defineConfig(() => {
  const isGitHubPages = process.env.GITHUB_ACTIONS === 'true';

  return {
    base: isGitHubPages ? '/MAESA-Skill/' : '/',
    css: { postcss: { plugins: [tailwindcss()] } },
    plugins: [vinext()],
  };
});
