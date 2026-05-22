import Foundation
import UIKit
import Vision

struct IngredientScanResult {
    let recognizedText: String
    let matches: [AdditiveMatch]
}

enum MatchConfidence {
    case sicher          // matched via E-number
    case wahrscheinlich  // matched via name (≥ 8 chars)
    case unsicher        // matched via short name (< 8 chars)

    var label: String {
        switch self {
        case .sicher: return "E-Nr."
        case .wahrscheinlich: return "Name"
        case .unsicher: return "Unsicher"
        }
    }
}

struct AdditiveMatch: Identifiable, Hashable {
    let id = UUID()
    let additive: Additive
    let matchedText: String
    let confidence: MatchConfidence

    func hash(into hasher: inout Hasher) {
        hasher.combine(id)
    }

    static func == (lhs: AdditiveMatch, rhs: AdditiveMatch) -> Bool {
        lhs.id == rhs.id
    }
}

struct DetectedAnimal: Hashable {
    let label: String
    let tokens: [String]
    let requiresFeedContext: Bool
}

struct IngredientScanService {
    func recognizeText(in image: UIImage) async throws -> String {
        guard let cgImage = image.cgImage else {
            throw IngredientScanError.invalidImage
        }

        return try await withCheckedThrowingContinuation { continuation in
            let request = VNRecognizeTextRequest { request, error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }

                let text = (request.results as? [VNRecognizedTextObservation])?
                    .compactMap { $0.topCandidates(1).first?.string }
                    .joined(separator: "\n") ?? ""
                continuation.resume(returning: text)
            }
            request.recognitionLevel = .accurate
            request.usesLanguageCorrection = true
            request.recognitionLanguages = ["de-DE", "en-US"]

            let handler = VNImageRequestHandler(cgImage: cgImage, orientation: image.cgImagePropertyOrientation)
            do {
                try handler.perform([request])
            } catch {
                continuation.resume(throwing: error)
            }
        }
    }

    func detectedAnimals(in recognizedText: String) -> [DetectedAnimal] {
        let normalizedText = normalize(recognizedText)
        guard !normalizedText.isEmpty else { return [] }

        return animalLexicon.filter { animal in
            animal.tokens.contains { token in
                let normalizedToken = normalize(token)
                if animal.requiresFeedContext {
                    return containsFeedTarget(normalizedToken, in: normalizedText)
                }
                return containsToken(normalizedToken, in: normalizedText)
            }
        }
    }

    func matchAdditives(in recognizedText: String, additives: [Additive]) -> [AdditiveMatch] {
        let normalizedText = normalize(recognizedText)
        guard !normalizedText.isEmpty else { return [] }

        let animals = detectedAnimals(in: recognizedText)

        var seen = Set<String>()
        var candidateMatches: [AdditiveMatch] = []

        for additive in additives {
            let eNumber = normalize(additive.eNumber)
            let name = normalize(additive.name)

            if !eNumber.isEmpty && containsENumber(eNumber, in: normalizedText) {
                append(additive: additive, matchedText: additive.eNumber, confidence: .sicher, seen: &seen, matches: &candidateMatches)
                continue
            }

            if name.count >= 4 && normalizedText.contains(name) {
                let confidence: MatchConfidence = name.count >= 8 ? .wahrscheinlich : .unsicher
                append(additive: additive, matchedText: additive.name, confidence: confidence, seen: &seen, matches: &candidateMatches)
            }
        }

        let matches = animalFilteredMatches(candidateMatches, detectedAnimals: animals)
        return matches.sorted {
            if $0.additive.eNumber == $1.additive.eNumber {
                return $0.additive.name < $1.additive.name
            }
            return $0.additive.eNumber < $1.additive.eNumber
        }
    }

    private func animalFilteredMatches(_ matches: [AdditiveMatch], detectedAnimals: [DetectedAnimal]) -> [AdditiveMatch] {
        guard !detectedAnimals.isEmpty else { return matches }

        let directMatches = matches.filter {
            matchesDetectedAnimals($0.additive, detectedAnimals: detectedAnimals)
                && !isGeneralAnimalEntry($0.additive)
        }
        if !directMatches.isEmpty {
            return directMatches + matches.filter { isGeneralAnimalEntry($0.additive) }
        }

        return matches.filter { isGeneralAnimalEntry($0.additive) }
    }

    private var animalLexicon: [DetectedAnimal] {
        [
            DetectedAnimal(label: "Hund", tokens: ["hund", "hunde", "hunden", "welpe", "welpen", "junghund", "junghunde", "dog", "dogs", "puppy", "puppies", "canine"], requiresFeedContext: false),
            DetectedAnimal(label: "Katze", tokens: ["katze", "katzen", "kitten", "kater", "cat", "cats", "feline"], requiresFeedContext: false),
            DetectedAnimal(label: "Geflügel", tokens: ["gefluegel", "geflugel", "huhn", "huehner", "huhner", "truthuhn", "truthuehner", "truthuhner", "pute", "puten", "ente", "enten", "gans", "gaense", "ganse", "chicken", "poultry", "turkey", "duck", "goose"], requiresFeedContext: true),
            DetectedAnimal(label: "Schwein", tokens: ["schwein", "schweine", "ferkel", "sau", "sauen", "pig", "pigs", "piglet", "swine"], requiresFeedContext: true),
            DetectedAnimal(label: "Rind", tokens: ["rind", "rinder", "kalb", "kaelber", "kalber", "kuh", "kuehe", "kuhe", "cattle", "cow", "calf", "bovine"], requiresFeedContext: true),
            DetectedAnimal(label: "Schaf", tokens: ["schaf", "schafe", "lamm", "laemmer", "lammer", "sheep", "lamb"], requiresFeedContext: true),
            DetectedAnimal(label: "Ziege", tokens: ["ziege", "ziegen", "goat", "goats"], requiresFeedContext: true),
            DetectedAnimal(label: "Pferd", tokens: ["pferd", "pferde", "fohlen", "horse", "horses", "foal"], requiresFeedContext: false),
            DetectedAnimal(label: "Fisch", tokens: ["fisch", "fische", "lachs", "forelle", "karpfen", "fish", "salmon", "trout", "carp"], requiresFeedContext: true),
            DetectedAnimal(label: "Kaninchen", tokens: ["kaninchen", "rabbit", "rabbits"], requiresFeedContext: false)
        ]
    }

    private func containsFeedTarget(_ token: String, in text: String) -> Bool {
        let patterns = [
            #"fuer\s+\w{0,20}\s*\#(token)\b"#,
            #"fur\s+\w{0,20}\s*\#(token)\b"#,
            #"für\s+\w{0,20}\s*\#(token)\b"#,
            #"for\s+\w{0,20}\s*\#(token)\b"#,
            #"\#(token)\s*futter\b"#,
            #"\#(token)\s*feed\b"#,
            #"\#(token)\s*alleinfuttermittel\b"#,
            #"\#(token)\s*ergaenzungsfuttermittel\b"#,
            #"\#(token)\s*erganzungsfuttermittel\b"#,
            #"\#(token)\s*ergänzungsfuttermittel\b"#
        ]

        return patterns.contains { pattern in
            text.range(of: pattern, options: .regularExpression) != nil
        }
    }

    private func matchesDetectedAnimals(_ additive: Additive, detectedAnimals: [DetectedAnimal]) -> Bool {
        guard !detectedAnimals.isEmpty else { return true }

        let species = normalize(additive.normalizedSpecies)
        let category = normalize(additive.animalCategory ?? "")

        if isGeneralAnimalEntry(additive) {
            return true
        }

        return detectedAnimals.contains { animal in
            animal.tokens.contains { token in
                let normalizedToken = normalize(token)
                return containsToken(normalizedToken, in: species) || containsToken(normalizedToken, in: category)
            }
        }
    }

    private func isGeneralAnimalEntry(_ additive: Additive) -> Bool {
        let species = normalize(additive.normalizedSpecies)
        let category = normalize(additive.animalCategory ?? "")
        return species.isEmpty
            || species.contains("alle tierarten")
            || category.contains("alle tierarten")
    }

    private func append(
        additive: Additive,
        matchedText: String,
        confidence: MatchConfidence,
        seen: inout Set<String>,
        matches: inout [AdditiveMatch]
    ) {
        let key = "\(additive.eNumber)|\(additive.name)|\(additive.normalizedSpecies)"
        guard !seen.contains(key) else { return }
        seen.insert(key)
        matches.append(AdditiveMatch(additive: additive, matchedText: matchedText, confidence: confidence))
    }

    private func containsToken(_ token: String, in text: String) -> Bool {
        let pattern = "(^|[^a-z0-9])\(NSRegularExpression.escapedPattern(for: token))([^a-z0-9]|$)"
        return text.range(of: pattern, options: .regularExpression) != nil
    }

    private func containsENumber(_ token: String, in text: String) -> Bool {
        if containsToken(token, in: text) {
            return true
        }

        let compactToken = token.replacingOccurrences(of: " ", with: "")
        let compactText = text.replacingOccurrences(of: " ", with: "")
        return containsToken(compactToken, in: compactText)
    }

    private func normalize(_ value: String) -> String {
        value
            .folding(options: [.diacriticInsensitive, .caseInsensitive], locale: .current)
            .lowercased()
            .replacingOccurrences(of: "−", with: "-")
            .replacingOccurrences(of: "\n", with: " ")
            .replacingOccurrences(of: #"[^a-z0-9*]+"#, with: " ", options: .regularExpression)
            .replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

enum IngredientScanError: LocalizedError {
    case invalidImage

    var errorDescription: String? {
        switch self {
        case .invalidImage:
            return "Das Bild konnte nicht verarbeitet werden."
        }
    }
}

private extension UIImage {
    var cgImagePropertyOrientation: CGImagePropertyOrientation {
        switch imageOrientation {
        case .up: return .up
        case .down: return .down
        case .left: return .left
        case .right: return .right
        case .upMirrored: return .upMirrored
        case .downMirrored: return .downMirrored
        case .leftMirrored: return .leftMirrored
        case .rightMirrored: return .rightMirrored
        @unknown default: return .up
        }
    }
}
