import { uploadEditorImage } from './images'
const post = vi.hoisted(() => vi.fn())
vi.mock('./client', async (original) => ({ ...await original<typeof import('./client')>(), api: { POST: post } }))
it('invia i byte del file e il lease nel multipart, conservando il riferimento relativo', async () => {
  const result = { path: 'assets/images/a.gif', name: 'a.gif', alt_text: 'Figura', url: '/api/v1/lessons/1/assets/images/a.gif' }
  post.mockResolvedValue({ data: result, response: { ok: true } })
  const file = new File(['GIF89a'], 'figura.gif', { type: 'image/gif' })
  expect(await uploadEditorImage(1, file, 'lease')).toEqual(result)
  const [path, options] = post.mock.calls[0]
  expect(path).toBe('/api/v1/lessons/{lesson_id}/media/images')
  expect(options.params.path.lesson_id).toBe(1)
  const form = options.bodySerializer()
  const uploaded = form.get('file') as File
  expect([uploaded.name, uploaded.type, uploaded.size]).toEqual(['figura.gif', 'image/gif', 6])
  const bytes = await new Promise((resolve) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.readAsText(uploaded) })
  expect(bytes).toBe('GIF89a')
  expect(form.get('lease_token')).toBe('lease')
})
