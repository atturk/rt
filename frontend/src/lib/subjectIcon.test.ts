import { describe, expect, it } from 'vitest'

import {
  SUBJECT_PALETTE,
  contrastRatio,
  iconLayout,
  subjectIcons,
  subjectInitials,
} from './subjectIcon'

const initials = (name: string, extra?: string[]) => subjectInitials(name, extra).join('')

describe('subjectInitials', () => {
  it.each([
    ['Anatomia', 'A'],
    ['Anatomia patologica', 'AP'],
    ['Patologia generale 1', 'PG1'],
    ['Anatomia e Fisiologia del Sistema Linfatico', 'AFSL'],
    ['Scienze della nutrizione umana', 'SNU'],
    ['Medicina d’urgenza', 'MU'],
    ["Medicina d'urgenza", 'MU'],
    ["Fisiologia dell'apparato digerente", 'FAD'],
    ['ANATOMIA PATOLOGICA', 'AP'],
  ])('%s → %s', (name, expected) => {
    expect(initials(name)).toBe(expected)
  })

  it('toglie la stoplist senza distinguere maiuscole e minuscole', () => {
    expect(initials('STORIA DELLA MEDICINA E DELLA CHIRURGIA')).toBe('SMC')
    expect(initials('Igiene ED Epidemiologia oppure Statistica')).toBe('IES')
  })

  it('tiene al massimo quattro parole significative', () => {
    expect(subjectInitials('Anatomia Fisiologia Biochimica Genetica Istologia')).toEqual(['A', 'F', 'B', 'G'])
  })

  it('numeri e numeri romani in fondo restano', () => {
    expect(subjectInitials('Patologia generale 12')).toEqual(['P', 'G', '12'])
    expect(subjectInitials('Anatomia II')).toEqual(['A', 'II'])
    expect(subjectInitials('Anatomia I')).toEqual(['A', 'I'])
    expect(initials('I tessuti')).toBe('T')
  })

  it('senza parole significative usa la prima lettera del nome', () => {
    expect(subjectInitials('Della')).toEqual(['D'])
    expect(subjectInitials("L'")).toEqual(['L'])
    expect(subjectInitials('—')).toEqual(['?'])
  })

  it('la stoplist si estende', () => {
    expect(initials('Corso di Anatomia', ['corso'])).toBe('A')
    expect(initials('Corso di Anatomia')).toBe('CA')
  })
})

describe('iconLayout', () => {
  it('sceglie la disposizione dal numero di iniziali', () => {
    expect([1, 2, 3, 4].map(iconLayout)).toEqual(['single', 'row', 'triangle', 'grid'])
  })

  it('le icone riportano la disposizione giusta', () => {
    const icons = subjectIcons(['Anatomia', 'Anatomia patologica', 'Patologia generale 1', 'Anatomia e Fisiologia del Sistema Linfatico'])
    expect(icons.get('ANATOMIA')?.layout).toBe('single')
    expect(icons.get('ANATOMIA PATOLOGICA')?.layout).toBe('row')
    expect(icons.get('PATOLOGIA GENERALE 1')?.layout).toBe('triangle')
    expect(icons.get('ANATOMIA E FISIOLOGIA DEL SISTEMA LINFATICO')?.layout).toBe('grid')
  })
})

describe('colori', () => {
  it('la palette ha almeno 12 colori distinti con contrasto AA', () => {
    expect(SUBJECT_PALETTE.length).toBeGreaterThanOrEqual(12)
    expect(new Set(SUBJECT_PALETTE.map((c) => c.bg)).size).toBe(SUBJECT_PALETTE.length)
    for (const c of SUBJECT_PALETTE) expect(contrastRatio(c.bg, c.fg)).toBeGreaterThanOrEqual(4.5)
  })

  it('è deterministico e non dipende da maiuscole o spazi', () => {
    const a = subjectIcons(['Biochimica', 'Anatomia']).get('BIOCHIMICA')
    const b = subjectIcons(['anatomia', '  BIOCHIMICA ']).get('BIOCHIMICA')
    expect(a?.color).toEqual(b?.color)
  })

  it('materie con le stesse iniziali hanno colori diversi', () => {
    const names = ['Biochimica', 'Biologia', 'Botanica', 'Batteriologia']
    const icons = subjectIcons(names)
    expect(names.map((n) => icons.get(n.toUpperCase())?.initials.join(''))).toEqual(['B', 'B', 'B', 'B'])
    expect(new Set(names.map((n) => icons.get(n.toUpperCase())?.color.bg)).size).toBe(4)
  })

  it('anche con tante materie dalle stesse iniziali, fino al numero dei colori', () => {
    const names = Array.from({ length: SUBJECT_PALETTE.length }, (_, i) => `Biologia${String.fromCharCode(97 + i)}`)
    const icons = subjectIcons(names)
    expect(new Set([...icons.values()].map((i) => i.color.bg)).size).toBe(SUBJECT_PALETTE.length)
  })

  it('aggiungere materie con altre iniziali non cambia i colori', () => {
    const base = ['Biochimica', 'Biologia', 'Botanica', 'Batteriologia', 'Anatomia']
    const before = subjectIcons(base)
    const after = subjectIcons([...base, 'Fisiologia', 'Farmacologia', 'Anatomia patologica', 'Chimica', 'Patologia generale 1'])
    for (const name of base) expect(after.get(name.toUpperCase())?.color).toEqual(before.get(name.toUpperCase())?.color)
  })
})
