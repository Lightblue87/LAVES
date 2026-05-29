import SwiftUI

struct SingleCheckView: View {
    @ObservedObject var store: AdditiveStore
    @ObservedObject var scanHistory: ScanHistoryService
    @Binding var selectedScanEntry: ScanEntry?

    @State private var animalCategory = "Alle Kategorien"
    @State private var selectedSpecies = "Alle Tierarten"
    @State private var eNumber = ""
    @State private var substance = ""
    @State private var value = ""
    @State private var result: EvaluationResult?
    @State private var lastAppliedScanID: UUID?
    @State private var isApplyingScanContext = false

    private let scanService = IngredientScanService()

    var body: some View {
        NavigationStack {
            Form {
                if let loadError = store.loadError {
                    Section {
                        Text(loadError)
                            .foregroundStyle(.red)
                    }
                }

                Section("Aktueller Scan") {
                    if let selectedScanEntry {
                        NavigationLink {
                            AdditiveScanResultView(entry: selectedScanEntry, store: store, scanHistory: scanHistory)
                        } label: {
                            HStack(spacing: 12) {
                                if let image = scanHistory.thumbnail(for: selectedScanEntry) {
                                    Image(uiImage: image)
                                        .resizable()
                                        .scaledToFill()
                                        .frame(width: 48, height: 48)
                                        .clipShape(RoundedRectangle(cornerRadius: 8))
                                } else {
                                    Image(systemName: "photo")
                                        .frame(width: 48, height: 48)
                                        .foregroundStyle(.secondary)
                                }

                                VStack(alignment: .leading, spacing: 3) {
                                    Text("Aktueller Scan")
                                        .font(.subheadline)
                                    Text(selectedScanEntry.timestamp.formatted(date: .abbreviated, time: .shortened))
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                        }
                    } else {
                        Text("Wähle oder erfasse einen Scan im Scan-Tab.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                Section("Kontext") {
                    Picker("Tierart-Kat.", selection: $animalCategory) {
                        ForEach(store.animalCategories, id: \.self) { category in
                            Text(category).tag(category)
                        }
                    }
                    .onChange(of: animalCategory) { _, _ in
                        guard !isApplyingScanContext else { return }
                        selectedSpecies = "Alle Tierarten"
                        resetAdditiveSelection()
                    }
                    Picker("Tierart", selection: $selectedSpecies) {
                        ForEach(store.species(for: animalCategory), id: \.self) { s in
                            Text(s).tag(s)
                        }
                    }
                    .onChange(of: selectedSpecies) { _, _ in
                        guard !isApplyingScanContext else { return }
                        resetAdditiveSelection()
                    }
                    if let selectedScanEntry,
                       let summary = scanContextSummary(for: selectedScanEntry) {
                        LabeledContent("Aus Scan erkannt", value: summary)
                            .font(.caption)
                    }
                }

                Section("Zusatzstoff") {
                    SearchableSelectionField(
                        title: "Zulassungsnummer",
                        placeholder: "Auswählen",
                        values: availableENumbers,
                        selection: $eNumber
                    )
                    .onChange(of: eNumber) { _, newValue in
                        result = nil
                        guard !newValue.isEmpty else { substance = ""; return }
                        let subs = EvaluationService.filteredSubstances(
                            in: store.additives, eNumber: newValue,
                            animalCategory: animalCategory, selectedSpecies: selectedSpecies
                        )
                        if subs.count == 1 { substance = subs[0] }
                    }
                    SearchableSelectionField(
                        title: "Stoffname",
                        placeholder: "Auswählen",
                        values: availableSubstances,
                        selection: $substance
                    )
                    .onChange(of: substance) { _, newValue in
                        result = nil
                        guard !newValue.isEmpty else { return }
                        if let derived = EvaluationService.eNumberForSubstance(
                            in: store.additives, substanceName: newValue,
                            animalCategory: animalCategory, selectedSpecies: selectedSpecies
                        ), eNumber != derived {
                            eNumber = derived
                        }
                    }
                    TextField("Laborwert (\(selectedUnit))", text: $value)
                        .keyboardType(.decimalPad)
                        .numericKeyboardToolbar()
                }

                Section {
                    Button("Prüfen") {
                        runCheck()
                    }
                    .disabled(Double(value.replacingOccurrences(of: ",", with: ".")) == nil)
                }

                if let result {
                    ResultSection(result: result)
                }

                DataStatusBanner(status: store.dataStatusBrief)
            }
            .scrollDismissesKeyboard(.interactively)
            .navigationTitle("Zusatzstoffe")
            .onAppear {
                applyScanContextIfNeeded()
            }
            .onChange(of: selectedScanEntry) { _, _ in
                applyScanContextIfNeeded(force: true)
            }
            .onChange(of: store.additives.count) { _, _ in
                applyScanContextIfNeeded()
            }
        }
    }

    private var availableENumbers: [String] {
        let filtered = EvaluationService.filteredENumbers(
            in: store.additives, substance: substance,
            animalCategory: animalCategory, selectedSpecies: selectedSpecies
        )
        return filtered.isEmpty ? store.eNumbers : filtered
    }

    private var availableSubstances: [String] {
        let filtered = EvaluationService.filteredSubstances(
            in: store.additives, eNumber: eNumber,
            animalCategory: animalCategory, selectedSpecies: selectedSpecies
        )
        return filtered.isEmpty ? store.substances : filtered
    }

    private var selectedUnit: String {
        let m = EvaluationService.candidates(
            in: store.additives, eNumber: eNumber, substance: substance,
            animalCategory: animalCategory, selectedSpecies: selectedSpecies
        )
        return m.first?.unit ?? "mg/kg"
    }

    private func resetAdditiveSelection() {
        eNumber = ""
        substance = ""
        result = nil
    }

    private func applyScanContextIfNeeded(force: Bool = false) {
        guard let entry = selectedScanEntry,
              !entry.ocrText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !store.additives.isEmpty else { return }
        guard force || lastAppliedScanID != entry.id else { return }

        isApplyingScanContext = true
        defer {
            DispatchQueue.main.async {
                isApplyingScanContext = false
            }
        }

        let animals = entry.analysisResult?.detectedSpeciesHints.isEmpty == false
            ? entry.analysisResult?.detectedSpeciesHints ?? []
            : scanService.detectedAnimals(in: entry.ocrText).map(\.label)

        if let context = bestAnimalContext(from: animals) {
            animalCategory = context.category
            selectedSpecies = context.species
        }

        if let match = bestAdditiveMatch(for: entry.ocrText) {
            if animalCategory == "Alle Kategorien",
               let category = match.additive.animalCategory,
               !category.isEmpty,
               store.animalCategories.contains(category) {
                animalCategory = category
            }
            eNumber = match.additive.eNumber
            substance = match.additive.name
            result = nil
        }

        lastAppliedScanID = entry.id
    }

    private func bestAnimalContext(from hints: [String]) -> (category: String, species: String)? {
        let normalizedHints = hints.map(normalizeForLookup).filter { !$0.isEmpty }
        guard !normalizedHints.isEmpty else { return nil }

        for category in store.animalCategories where category != "Alle Kategorien" {
            let species = store.species(for: category)
            for candidate in species where candidate != "Alle Tierarten" {
                let normalizedCandidate = normalizeForLookup(candidate)
                if normalizedHints.contains(where: {
                    normalizedCandidate.contains($0) || $0.contains(normalizedCandidate)
                }) {
                    return (category, candidate)
                }
            }
        }

        for additive in store.additives {
            guard let category = additive.animalCategory,
                  category != "Alle Tierarten",
                  store.animalCategories.contains(category) else { continue }
            let extracted = EvaluationService.extractIndividualSpecies(
                from: additive.normalizedSpecies,
                category: category
            )
            for candidate in extracted {
                let normalizedCandidate = normalizeForLookup(candidate)
                if normalizedHints.contains(where: {
                    normalizedCandidate.contains($0) || $0.contains(normalizedCandidate)
                }) {
                    return (category, candidate)
                }
            }
        }

        return nil
    }

    private func bestAdditiveMatch(for text: String) -> AdditiveMatch? {
        scanService.matchAdditives(in: text, additives: store.additives)
            .sorted { lhs, rhs in
                score(lhs) > score(rhs)
            }
            .first
    }

    private func score(_ match: AdditiveMatch) -> Int {
        switch match.confidence {
        case .sicher: return 3
        case .wahrscheinlich: return 2
        case .unsicher: return 1
        }
    }

    private func scanContextSummary(for entry: ScanEntry) -> String? {
        var parts: [String] = []
        let animals = entry.analysisResult?.detectedSpeciesHints ?? []
        if !animals.isEmpty {
            parts.append(animals.joined(separator: ", "))
        }
        if let names = entry.analysisResult?.additiveHints.detectedSubstanceNames,
           !names.isEmpty {
            parts.append(names.prefix(2).joined(separator: ", "))
        } else if entry.analysisResult?.additiveHints.hasENumbers == true {
            parts.append("E-Nummer")
        } else if entry.analysisResult?.additiveHints.hasAdditiveSection == true {
            parts.append("Zusatzstoffe")
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private func normalizeForLookup(_ value: String) -> String {
        value
            .folding(options: [.diacriticInsensitive, .caseInsensitive], locale: .current)
            .lowercased()
            .replacingOccurrences(of: #"[^a-z0-9]+"#, with: "", options: .regularExpression)
    }

    private func runCheck() {
        guard let numberValue = Double(value.replacingOccurrences(of: ",", with: ".")) else {
            return
        }

        let matches = EvaluationService.candidates(
            in: store.additives,
            eNumber: eNumber,
            substance: substance,
            animalCategory: animalCategory,
            selectedSpecies: selectedSpecies
        )

        guard let additive = matches.first else {
            result = EvaluationResult(state: .nichtBewertbar, lines: ["Kein passender Datensatz gefunden."])
            return
        }

        if matches.count > 1 {
            result = EvaluationResult(
                state: .nichtBewertbar,
                lines: [
                    "Mehrere passende Datensätze gefunden.",
                    "Bitte Zulassungsnummer oder Stoffname genauer eingrenzen.",
                    "Treffer: \(matches.prefix(5).map(\.displayTitle).joined(separator: ", "))"
                ]
            )
            return
        }

        result = EvaluationService.evaluate(value: numberValue, additive: additive)
    }
}

struct ResultSection: View {
    let result: EvaluationResult

    var body: some View {
        Section {
            VStack(alignment: .leading, spacing: 8) {
                Label(result.state.title, systemImage: result.state.icon)
                    .font(.headline)
                    .foregroundStyle(color)
                ForEach(result.lines, id: \.self) { line in
                    Text(line)
                        .font(.body)
                }
                Divider()
                Text(EvaluationState.schnellcheckDisclaimer)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(.vertical, 4)
        }
    }

    private var color: Color {
        switch result.state {
        case .unauffaellig: return .green
        case .auffaellig: return .red
        case .nichtBewertbar: return .orange
        }
    }
}

struct DataStatusBanner: View {
    let status: String

    var body: some View {
        Section {
            HStack(spacing: 6) {
                Image(systemName: "cylinder.split.1x2")
                    .foregroundStyle(.secondary)
                Text(status)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }
}
