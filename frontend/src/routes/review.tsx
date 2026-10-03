import { Navigate, useLocation, useParams } from 'react-router'

/** I collegamenti salvati aprono la verifica dentro la lezione. */
export function ReviewPage() {
  const { lessonId } = useParams()
  const { search, hash } = useLocation()
  const query = new URLSearchParams(search)
  query.set('pannello', 'verifica')
  return <Navigate replace to={`/lezioni/${lessonId}?${query}${hash}`} />
}
