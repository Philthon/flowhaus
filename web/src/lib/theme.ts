/** Follow the computer's light or dark setting, live: the dark colours apply under `.dark` (see index.css). */
export function followSystemTheme(): void {
  const query = window.matchMedia?.("(prefers-color-scheme: dark)");
  const apply = () => document.documentElement.classList.toggle("dark", !!query?.matches);
  apply();
  query?.addEventListener?.("change", apply);
}
