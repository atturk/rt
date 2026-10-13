import { EditorState } from '@codemirror/state'
import type { EditorView } from '@codemirror/view'
import { act, render, screen } from '@testing-library/react'
import { useEffect } from 'react'

import { AudioProvider, useLessonAudio } from './audio'
import { EditorAudioLines } from './EditorAudioLines'

const markdown = '# Lezione\n\n### 1.1 Primo\n\nTesto uno.\n\n### 1.2 Secondo\n\nTesto due.'
// Vista finta: ogni riga alta 20 px, documento a 100 px dalla cima dell'editor.
function fakeView(): EditorView {
  const state = EditorState.create({ doc: markdown })
  const dom = document.createElement('div')
  dom.getBoundingClientRect = () => ({ top: 0 }) as DOMRect
  return {
    state,
    dom,
    documentTop: 100,
    lineBlockAt: (pos: number) => {
      const n = state.doc.lineAt(pos).number - 1
      return { top: n * 20, bottom: n * 20 + 20 }
    },
  } as unknown as EditorView
}

const sections = [
  { unit_id: '1.1', title: 'Primo', start_segment_id: 's1', end_segment_id: 's2', start_seconds: 0, end_seconds: 60, speech_segments: [[0, 40], [50, 60]] },
  { unit_id: '1.2', title: 'Secondo', start_segment_id: 's3', end_segment_id: 's4', start_seconds: 60, end_seconds: 120, speech_segments: [[60, 120]] },
]

function At({ time }: { time: number }) {
  const { setCurrentTime } = useLessonAudio()
  useEffect(() => setCurrentTime(time), [time, setCurrentTime])
  return null
}

describe('EditorAudioLines (AU1 nel testo della lezione)', () => {
  it("segna l'unità che si ascolta e lascia la traccia su quelle ascoltate", () => {
    const view = fakeView()
    const ui = (time: number) => (
      <AudioProvider>
        <At time={time} />
        <EditorAudioLines view={view} sections={sections as never} />
      </AudioProvider>
    )
    const { rerender } = render(ui(20))
    const first = screen.getByTestId('audio-line-1.1')
    expect(first).toHaveAttribute('data-active', 'true')
    // dal titolo (riga 3) alla fine dell'unità (riga 5)
    expect(first).toHaveStyle({ top: '140px', height: '60px' })
    expect(first.querySelector('i')).toHaveStyle({ height: '40%' })
    expect(screen.queryByTestId('audio-line-1.2')).toBeNull()

    // nella pausa fra 40 e 50 s la linea non avanza
    act(() => rerender(ui(45)))
    expect(screen.getByTestId('audio-line-1.1').querySelector('i')).toHaveStyle({ height: '80%' })

    act(() => rerender(ui(90)))
    expect(screen.getByTestId('audio-line-1.1')).toHaveAttribute('data-done', 'true')
    expect(screen.getByTestId('audio-line-1.2')).toHaveAttribute('data-active', 'true')
  })

  it("senza editor non disegna niente", () => {
    render(<AudioProvider><EditorAudioLines view={null} sections={sections as never} /></AudioProvider>)
    expect(screen.queryByTestId('audio-speech-lines')).toBeNull()
  })
})
