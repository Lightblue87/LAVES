import SwiftUI

struct BatchCheckView: View {
    @ObservedObject var store: AdditiveStore

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
                Section("Partie") {
                    TextField("Partiemenge", text: $batchValue)
                        .keyboardType(.decimalPad)
                    Picker("Einheit", selection: $batchUnit) {
                        ForEach(units, id: \.self) { unit in
                            Text(unit).tag(unit)
                        }
                    }
                }

                Section("Zusatzstoff") {
                    TextField("Zulassungsnummer", text: $eNumber)
                        .textInputAutocapitalization(.characters)
                    TextField("Stoffname", text: $substance)
                    TextField("% der Gesamtpartie", text: $percent)
                        .keyboardType(.decimalPad)
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
            }
            .navigationTitle("Zusatzstoffprüfung")
        }
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
            animalCategory: "Alle Kategorien"
        )

        guard let additive = matches.first, matches.count == 1 else {
            result = EvaluationResult(
                state: .warning,
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
