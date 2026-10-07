/** I limiti riguardano l’intero Studio, anche quando comprende più lezioni. */
export function studyNavigation(direction: -1 | 1, unit: number, units: number, lesson: number, lessons: number) {
  if (direction === -1) return unit > 0 ? 'previous-unit' : lesson > 0 ? 'previous-lesson' : 'left-edge'
  return unit + 1 < units ? 'next-unit' : lesson + 1 < lessons ? 'next-lesson' : 'right-edge'
}
