import { useQuery } from '@tanstack/react-query'
import { api, unwrap } from './client'
export function useClassifier(id: number) {
 return useQuery({queryKey:['classifier',id],enabled:Number.isFinite(id),queryFn:()=>unwrap(api.GET('/api/v1/lessons/{lesson_id}/classifier',{params:{path:{lesson_id:id}}})),refetchInterval:5000})
}
