import { describe, expect, it } from 'vitest'

import { recordingFormat } from './recording'

describe('recordingFormat', () => {
  it('preferisce webm e ne usa l\'estensione accettata dall\'API', () => {
    expect(recordingFormat(() => true)).toEqual({ mimeType: 'audio/webm', extension: 'webm' })
  })
  it('su Safari registra in mp4 e invia .m4a', () => {
    expect(recordingFormat((t) => t === 'audio/mp4')).toEqual({ mimeType: 'audio/mp4', extension: 'm4a' })
  })
  it('senza formati noti lascia scegliere al browser', () => {
    expect(recordingFormat(() => false)).toEqual({ extension: 'webm' })
  })
})
