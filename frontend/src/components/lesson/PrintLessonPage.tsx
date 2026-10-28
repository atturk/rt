import { useEffect, useRef } from 'react'
import { useParams } from 'react-router'

import { useLesson, useLessonDocument } from '@/api/hooks'
import { lessonTitle } from '@/lib/format'
import { withImageUrls } from '@/lib/images'
import { shortDate, subjectName } from '@/lib/lessonsPage'
import { renderDelimitedMath } from '@/lib/math'
import { transformPrintDom, waitForImagesLoaded } from '@/lib/printDocument'

export function PrintLessonPage() {
  const { lessonId } = useParams()
  const id = Number(lessonId)
  const lessonQuery = useLesson(id)
  const docQuery = useLessonDocument(id)
  const rootRef = useRef<HTMLDivElement>(null)

  const lesson = lessonQuery.data
  const doc = docQuery.data

  useEffect(() => {
    delete document.body.dataset.ready
    const root = rootRef.current
    if (!root || !doc) return

    // Prepara l'HTML con le immagini ridotte a max=1600
    const rawHtml = withImageUrls(doc.html, id, 1600)
    root.innerHTML = rawHtml
    // Il timecode va solo accanto al titolo: qui non c'è .rt-document che nasconde il paragrafo.
    root.querySelectorAll('[data-unit-timecode]').forEach((el) => el.remove())

    // Aggiungi i timecode accanto al titolo della sottounità (in grigio 8,5 pt)
    for (const section of doc.sections || []) {
      if (!section.start_formatted) continue
      const heading = root.querySelector<HTMLElement>(`[data-unit-id="${CSS.escape(section.unit_id)}"]`)
      if (!heading) continue
      const tc = document.createElement('span')
      tc.className = 'print-timecode'
      tc.textContent = ` ${section.start_formatted}`
      heading.appendChild(tc)
    }

    void (async () => {
      // Formule temml
      await renderDelimitedMath(root)
      // Griglia a 2 colonne per le immagini
      transformPrintDom(root)
      // Attendi caricamento immagini
      await waitForImagesLoaded(root)
      // Segnala a Playwright che la pagina è pronta per page.pdf
      document.body.dataset.ready = '1'
    })()

    return () => {
      delete document.body.dataset.ready
    }
  }, [doc, lesson, id])

  if (!lesson || !doc) {
    return null
  }

  const metaParts = [
    lesson.materia ? subjectName(lesson.materia) : null,
    lesson.data ? shortDate(lesson.data) : null,
  ].filter(Boolean)

  return (
    <article className="print-page">
      <style>{`
        @page {
          size: A4;
          margin: 20mm 18mm 18mm 18mm;
        }
        body {
          margin: 0;
          background: #ffffff;
        }
        .print-page {
          font-family: serif;
          font-size: 10.5pt;
          line-height: 1.5;
          text-align: justify;
          hyphens: auto;
          color: #111827;
          background: #ffffff;
          box-sizing: border-box;
          max-width: 174mm;
          margin: 0 auto;
          padding: 20mm 18mm;
        }
        @media print {
          .print-page {
            max-width: none;
            padding: 0;
            margin: 0;
          }
        }
        .print-header {
          font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
          font-size: 9pt;
          color: #6b7280;
          margin-bottom: 2mm;
        }
        .print-title {
          font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
          font-size: 19pt;
          font-weight: 700;
          line-height: 1.25;
          margin-top: 0;
          margin-bottom: 6mm;
          text-align: left;
        }
        .print-content h2 {
          font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
          font-size: 14pt;
          font-weight: 700;
          break-after: avoid;
          margin-top: 1.4em;
          margin-bottom: 0.4em;
          text-align: left;
        }
        .print-content h3 {
          font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
          font-size: 11.5pt;
          font-weight: 700;
          break-after: avoid;
          margin-top: 1.2em;
          margin-bottom: 0.3em;
          text-align: left;
        }
        .print-content p {
          margin-top: 0;
          margin-bottom: 0.8em;
        }
        .print-timecode {
          font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
          font-size: 8.5pt;
          font-weight: 400;
          color: #6b7280;
          margin-left: 0.4em;
        }
        .print-content img {
          max-width: 100%;
          height: auto;
          break-inside: avoid;
        }
        .pdf-image-grid {
          margin: 4mm 0;
          width: 100%;
        }
        .pdf-image-grid.pdf-grid-single {
          display: flex;
          justify-content: center;
        }
        .pdf-image-grid.pdf-grid-single .pdf-image-card {
          width: calc(50% - 2.5mm);
          max-width: 85mm;
          break-inside: avoid;
        }
        .pdf-image-grid.pdf-grid-multi {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          column-gap: 5mm;
          row-gap: 4mm;
        }
        .pdf-image-card {
          margin: 0;
          break-inside: avoid;
          display: flex;
          flex-direction: column;
          align-items: center;
        }
        .pdf-card-last-odd {
          grid-column: 1 / -1;
          justify-self: center;
          width: calc(50% - 2.5mm);
        }
        .pdf-img {
          max-height: 95mm;
          object-fit: contain;
          border: 1px solid #e5e7eb;
          border-radius: 1.2mm;
          display: block;
          width: 100%;
          box-sizing: border-box;
        }
        .pdf-image-caption {
          font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
          font-size: 8pt;
          color: #6b7280;
          text-align: center;
          margin-top: 2mm;
        }
      `}</style>

      {metaParts.length > 0 && (
        <div className="print-header">
          {metaParts.join(' · ')}
        </div>
      )}

      <h1 className="print-title">
        {lessonTitle(lesson)}
      </h1>

      <div ref={rootRef} className="print-content" />
    </article>
  )
}
