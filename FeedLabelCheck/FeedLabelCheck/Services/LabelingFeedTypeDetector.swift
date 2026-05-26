import Foundation

struct LabelingFeedTypeDetector {

    struct DetectionResult {
        let feedType: LabelingFeedType
        let confidence: Double         // 0.0 – 1.0
        let matchedKeywords: [String]
        let score: Double
    }

    func detect(in ocrText: String, feedTypes: [LabelingFeedType]) -> DetectionResult? {
        let normalized = normalize(ocrText)
        guard !normalized.isEmpty else { return nil }

        let candidates = rankedCandidates(in: normalized, feedTypes: feedTypes)

        guard let best = candidates.first else { return nil }

        // Force manual selection only for genuinely close, same-strength
        // legal feed type hits. Generic pet-feed words should not override
        // explicit labels such as "Alleinfuttermittel".
        if candidates.count > 1 && (best.score - candidates[1].score) < 0.25 {
            return nil
        }

        return best
    }

    func detectAmbiguous(in ocrText: String, feedTypes: [LabelingFeedType]) -> [DetectionResult] {
        let normalized = normalize(ocrText)
        return rankedCandidates(in: normalized, feedTypes: feedTypes)
    }

    private func rankedCandidates(in normalized: String, feedTypes: [LabelingFeedType]) -> [DetectionResult] {
        guard !normalized.isEmpty else { return [] }

        return feedTypes
            .filter { $0.id != "all" && $0.id != "unknown" }
            .compactMap { feedType -> DetectionResult? in
                let matched = matchedKeywords(for: feedType, in: normalized)
                guard !matched.isEmpty else { return nil }

                let bestKeyword = matched
                    .map { keywordScore($0, feedTypeId: feedType.id) }
                    .max() ?? 0
                let score = feedTypePriority(feedType.id) + bestKeyword + min(Double(matched.count) * 0.05, 0.2)
                let confidence = min(1.0, max(0.55, score / 4.5))

                return DetectionResult(
                    feedType: feedType,
                    confidence: confidence,
                    matchedKeywords: matched,
                    score: score
                )
            }
            .sorted {
                if $0.score == $1.score {
                    return $0.feedType.id < $1.feedType.id
                }
                return $0.score > $1.score
            }
    }

    private func matchedKeywords(for feedType: LabelingFeedType, in normalized: String) -> [String] {
        feedType.keywordsDe.filter { keyword in
            let nk = normalize(keyword)
            guard !nk.isEmpty else { return false }
            if directLegalTerms.contains(nk) {
                return containsPhrase(nk, in: normalized)
            }
            return normalized.contains(nk)
        }
    }

    private func keywordScore(_ keyword: String, feedTypeId: String) -> Double {
        let normalizedKeyword = normalize(keyword)
        if directLegalTerms.contains(normalizedKeyword) {
            return 2.0
        }
        if feedTypeId == "pet_feed" {
            return 0.35
        }
        return 1.0
    }

    private func feedTypePriority(_ feedTypeId: String) -> Double {
        switch feedTypeId {
        case "complete_feed", "complementary_feed", "single_feed", "compound_feed",
             "mineral_feed", "milk_replacer":
            return 2.0
        case "pet_feed":
            return 0.8
        default:
            return 1.0
        }
    }

    private var directLegalTerms: Set<String> {
        [
            "einzelfuttermittel",
            "mischfuttermittel",
            "alleinfuttermittel",
            "allein-futtermittel",
            "alleinfutter",
            "diat alleinfuttermittel",
            "diaet alleinfuttermittel",
            "erganzungsfuttermittel",
            "ergaenzungsfuttermittel",
            "erganzungsfutermittel",
            "ergaenzungsfutermittel",
            "erganzungsfuttermitel",
            "ergaenzungsfuttermitel",
            "erganzungsfutter",
            "mineralfuttermittel",
            "mineral-futtermittel",
            "mineralfutter",
            "milchaustauscher",
            "milch-austauscher"
        ]
    }

    private func containsPhrase(_ phrase: String, in text: String) -> Bool {
        let escaped = NSRegularExpression.escapedPattern(for: phrase)
        let pattern = "(^|[^a-z0-9])\(escaped)([^a-z0-9]|$)"
        guard let regex = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]) else {
            return text.contains(phrase)
        }
        let range = NSRange(text.startIndex..., in: text)
        return regex.firstMatch(in: text, options: [], range: range) != nil
    }

    private func normalize(_ text: String) -> String {
        text.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: .current).lowercased()
    }
}
