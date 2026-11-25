import { describe, expect, it } from 'vitest'
import { lessonTopics, topicsAndKeywordsText } from './lessonTopics'

describe('lessonTopics', () => {
  it('usa le voci generate quando info.yaml le ha solo unite con virgole', () => {
    const generated = ['Biosintesi, secrezione e regolazione dell\'insulina', 'Ruolo del glucagone']
    expect(lessonTopics(generated.join(', '), generated)).toEqual(generated)
  })

  it('divide gli argomenti scritti a mano', () => {
    expect(lessonTopics('Insulina; Glucagone, Incretine', ['Altro'])).toEqual(['Insulina', 'Glucagone', 'Incretine'])
    expect(lessonTopics('', ['Generato'])).toEqual(['Generato'])
  })
})

describe('topicsAndKeywordsText', () => {
  it('mette prima gli argomenti e poi le keywords di tutte le unità, una per riga', () => {
    const text = topicsAndKeywordsText(['Omeostasi glicemica'], [
      { key_concepts: ['Insulina', 'GLUT4 (muscolo, tessuto adiposo)'] },
      { key_concepts: [] },
      { key_concepts: ['Glucagone', 'Insulina'] },
    ])
    expect(text).toBe('Omeostasi glicemica\nInsulina\nGLUT4 (muscolo, tessuto adiposo)\nGlucagone')
  })
})
