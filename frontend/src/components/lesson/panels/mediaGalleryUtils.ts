import type { LessonImage } from '@/api/images'

export type MediaGroup = {
  name: string
  images: LessonImage[]
  usedCount: number
  totalCount: number
  flatStartIndex: number
}

export function groupMediaImages(images: LessonImage[]): MediaGroup[] {
  const map = new Map<string, LessonImage[]>()
  for (const img of images) {
    const key =
      img.source_name ||
      (img.source === 'web'
        ? 'Dal web'
        : img.source === 'editor' || img.source === 'upload'
          ? "Dall'editor"
          : img.source === 'enrichment'
            ? 'Arricchimento'
            : 'Altre immagini')
    if (!map.has(key)) {
      map.set(key, [])
    }
    map.get(key)!.push(img)
  }

  const groups: MediaGroup[] = []
  let runningIndex = 0
  for (const [name, imgs] of map.entries()) {
    const usedCount = imgs.filter((i) => i.in_document).length
    groups.push({
      name,
      images: imgs,
      usedCount,
      totalCount: imgs.length,
      flatStartIndex: runningIndex,
    })
    runningIndex += imgs.length
  }
  return groups
}
