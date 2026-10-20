export function selectPage(
  selected: number[],
  number: number,
  numbers: number[],
  anchor: number | null,
  shift: boolean,
  additive: boolean,
): number[] {
  if (shift && anchor !== null) {
    const first = numbers.indexOf(anchor),
      last = numbers.indexOf(number)
    return numbers.slice(Math.min(first, last), Math.max(first, last) + 1)
  }
  if (additive)
    return selected.includes(number)
      ? selected.filter((n) => n !== number)
      : [...selected, number].sort((a, b) => a - b)
  return selected.length === 1 && selected[0] === number ? [] : [number]
}
