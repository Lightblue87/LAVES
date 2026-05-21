import Foundation

@MainActor
final class AdditiveStore: ObservableObject {
    @Published private(set) var additives: [Additive] = []
    @Published private(set) var loadError: String?

    var eNumbers: [String] {
        Array(Set(additives.map(\.eNumber).filter { !$0.isEmpty })).sorted()
    }

    var substances: [String] {
        Array(Set(additives.map(\.name).filter { !$0.isEmpty })).sorted()
    }

    var animalCategories: [String] {
        let categories = Set(additives.compactMap(\.animalCategory).filter { !$0.isEmpty })
        return ["Alle Kategorien"] + categories.sorted()
    }

    func load() {
        guard additives.isEmpty else { return }
        guard let url = Bundle.main.url(forResource: "zusatzstoffe", withExtension: "json") else {
            loadError = "zusatzstoffe.json wurde im App-Bundle nicht gefunden."
            return
        }

        do {
            let data = try Data(contentsOf: url)
            additives = try JSONDecoder().decode([Additive].self, from: data)
            loadError = nil
        } catch {
            loadError = "Daten konnten nicht geladen werden: \(error.localizedDescription)"
        }
    }
}
