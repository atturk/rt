import { EditorState } from '@codemirror/state'
import { imageSections } from './imageSections'

it('le immagini sotto il titolo di una sezione (## N.) vanno nella sua graffetta', () => {
  const doc = [
    '## 7. Entropia',
    '',
    '![Pagina 1](assets/images/a.png)',
    '',
    '![Pagina 2](assets/images/b.png)',
    '',
    '### 7.1 Formula',
    '12:34',
    '![Pagina 3](assets/images/c.png)',
    'Testo.',
  ].join('\n')
  const sections = imageSections(EditorState.create({ doc }))
  expect(sections.map(section => [section.id, section.images.map(image => image.name)])).toEqual([
    ['7', ['a.png', 'b.png']],
    ['7.1', ['c.png']],
  ])
})
