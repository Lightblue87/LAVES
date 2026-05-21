import SwiftUI

struct SingleCheckView: View {
    @ObservedObject var store: AdditiveStore

    @State private var animalCategory = "Alle Kategorien"
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
                }

                Section("Zusatzstoff") {
                    TextField("Zulassungsnummer", text: $eNumber)
                        .textInputAutocapitalization(.characters)
                    TextField("Stoffname", text: $substance)
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
            .navigationTitle("LAVES")
        }
    }

    private func runCheck() {
        guard let numberValue = Double(value.replacingOccurrences(of: ",", with: ".")) else {
            return
        }

        let matches = EvaluationService.candidates(
            in: store.additives,
            eNumber: eNumber,
            substance: substance,
            animalCategory: animalCategory
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
