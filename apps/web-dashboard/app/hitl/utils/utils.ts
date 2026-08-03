import { HitlRequest } from "@/types"

export const getHitlReview = (req: HitlRequest) => {
    return req.payload?.hitl_review || req.payload?.payload?.hitl_review || null
}

export const defaultEditablePayload = (req: HitlRequest): string => {
    const review = getHitlReview(req)
    const proposed = review?.proposed_extracted_data
    if (proposed && Object.keys(proposed).length > 0) {
        return JSON.stringify(proposed, null, 2)
    }
    return JSON.stringify(req.payload?.extracted_data || req.payload, null, 2)
}