import SwiftUI

struct SingleCheckView: View {
    @ObservedObject var store: AdditiveStore

    @State private var animalCategory = "Alle Kategorien"
    @State private var selectedSpecies = "Alle Tierarten"
    @State private var eNumber = ""
    @State private var substance = ""
    @State private var value = ""
    @State private var result: EvaluationResult?

    var body: some View {
        NavigationStack {
            Form {
                if let loadError = store.loadError {
                    Section {
                        Text(loadError)
                            .foregroundStyle(.red)
                    }
                }

                Section("Kontext") {
                    Picker("Tierart-Kat.", selection: $animalCategory) {
                        ForEach(store.animalCategories, id: \.self) { category in
                            Text(category).tag(category)
                        }
                    }
                    .onChange(of: animalCategory) { _, _ in
                        selectedSpecies = "Alle Tierarten"
                        resetAdditiveSelection()
                    }
                    Picker("Tierart", selection: $selectedSpecies) {
                        ForEach(store.species(for: animalCategory), id: \.self) { s in
                            Text(s).tag(s)
                        }
                    }
                    .onChange(of: selectedSpecies) { _, _ in
                        resetAdditiveSelection()
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
                    TextField("Laborwert mg/kg", text: $value)
                        .keyboardType(.decimalPad)
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
            }
            .navigationTitle("Einzelprüfung")
        }
    }

    private var availableENumbers: [String] {
        guard !substance.isEmpty else { return store.eNumbers }
        let filtered = EvaluationService.filteredENumbers(
            in: store.additives, substance: substance,
            animalCategory: animalCategory, selectedSpecies: selectedSpecies
        )
        return filtered.isEmpty ? store.eNumbers : filtered
    }

    private var availableSubstances: [String] {
        guard !eNumber.isEmpty else { return store.substances }
        let filtered = EvaluationService.filteredSubstances(
            in: store.additives, eNumber: eNumber,
            animalCategory: animalCategory, selectedSpecies: selectedSpecies
        )
        return filtered.isEmpty ? store.substances : filtered
    }

    private func resetAdditiveSelection() {
        eNumber = ""
        substance = ""
        result = nil
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
            result = EvaluationResult(state: .warning, lines: ["Kein passender Datensatz gefunden."])
            return
        }

        if matches.count > 1 {
            result = EvaluationResult(
                state: .warning,
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
                Text(result.state.title)
                    .font(.headline)
                    .foregroundStyle(color)
                ForEach(result.lines, id: \.self) { line in
                    Text(line)
                        .font(.body)
                }
            }
            .padding(.vertical, 4)
        }
    }

    private var color: Color {
        switch result.state {
        case .compliant: return .green
        case .nonCompliant: return .red
        case .warning: return .orange
        }
    }
}
