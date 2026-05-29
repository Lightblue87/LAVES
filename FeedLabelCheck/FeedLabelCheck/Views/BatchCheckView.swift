import SwiftUI

struct BatchCheckView: View {
    @ObservedObject var store: AdditiveStore

    @State private var animalCategory = "Alle Kategorien"
    @State private var selectedSpecies = "Alle Tierarten"
    @State private var batchValue = ""
    @State private var batchUnit = "kg"
    @State private var eNumber = ""
    @State private var substance = ""
    @State private var percent = ""
    @State private var result: EvaluationResult?

    private let units = ["g", "kg", "t"]

    var body: some View {
        NavigationStack {
            Form {
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

                Section("Partie") {
                    TextField("Partiemenge", text: $batchValue)
                        .keyboardType(.decimalPad)
                        .numericKeyboardToolbar()
                    Picker("Einheit", selection: $batchUnit) {
                        ForEach(units, id: \.self) { unit in
                            Text(unit).tag(unit)
                        }
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
                    TextField("% der Gesamtpartie", text: $percent)
                        .keyboardType(.decimalPad)
                        .numericKeyboardToolbar()
                }

                Section {
                    Button("Prüfen") {
                        runCheck()
                    }
                    .disabled(!inputIsValid)
                }

                if let result {
                    ResultSection(result: result)
                }

                DataStatusBanner(status: store.dataStatusBrief)
            }
            .scrollDismissesKeyboard(.interactively)
            .navigationTitle("Zusatzstoffprüfung")
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

    private var inputIsValid: Bool {
        parse(batchValue) != nil && parse(percent) != nil
    }

    private func runCheck() {
        guard let batch = parse(batchValue), let pct = parse(percent) else {
            return
        }

        let batchKg = EvaluationService.batchKg(value: batch, unit: batchUnit)
        let mass = EvaluationService.massKg(batchKg: batchKg, percent: pct)
        let concentration = EvaluationService.batchConcentrationMgKg(percent: pct)

        let matches = EvaluationService.candidates(
            in: store.additives,
            eNumber: eNumber,
            substance: substance,
            animalCategory: animalCategory,
            selectedSpecies: selectedSpecies
        )

        guard let additive = matches.first, matches.count == 1 else {
            result = EvaluationResult(
                state: .nichtBewertbar,
                lines: [
                    matches.isEmpty ? "Kein passender Datensatz gefunden." : "Mehrere passende Datensätze gefunden.",
                    "Masse: \(mass.formatted(.number.precision(.fractionLength(0...3)))) kg",
                    "Konzentration: \(concentration.formatted(.number.precision(.fractionLength(0...3)))) mg/kg"
                ]
            )
            return
        }

        let evaluation = EvaluationService.evaluate(value: concentration, additive: additive)
        result = EvaluationResult(
            state: evaluation.state,
            lines: [
                "Anteil: \(pct.formatted(.number.precision(.fractionLength(0...3)))) %",
                "Masse: \(mass.formatted(.number.precision(.fractionLength(0...3)))) kg",
                "Konzentration: \(concentration.formatted(.number.precision(.fractionLength(0...3)))) mg/kg"
            ] + evaluation.lines
        )
    }

    private func parse(_ text: String) -> Double? {
        Double(text.replacingOccurrences(of: ",", with: "."))
    }
}
