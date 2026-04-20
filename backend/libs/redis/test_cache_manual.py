"""
Test manuel du cache Redis avec Supabase.

Ce fichier teste toutes les fonctionnalités du cache avec de vraies données Supabase.
Exécutez avec: python -m app.libs.redis.test_cache_manual
"""

import time
import hashlib
import os
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
from libs.redis import CacheManager
from libs.supabase.supabase import SupabaseManager
from libs.log_manager.controller import LoggingController
from libs.log_manager.core.utils import get_correlation_id

# Charger les variables d'environnement
load_dotenv("docker/config/env/.env.shared")

# Override Redis host pour test local
os.environ["REDIS_HOST"] = "localhost"


class CacheTester:
    """Testeur pour les fonctionnalités de cache avec Supabase."""

    def __init__(self):
        self.logger = LoggingController(app_name="CacheTester")
        self.cache = CacheManager(default_ttl=300)  # 5 minutes par défaut
        self.supabase = SupabaseManager()

    def test_1_basic_cache_operations(self):
        """Test 1: Opérations de base du cache."""
        print("\n=== Test 1: Opérations de base du cache ===")
        correlation_id = get_correlation_id()

        # Test set/get simple
        test_data = {"message": "Hello Cache!", "timestamp": time.time()}

        print("1.1 Test set/get simple...")
        self.cache.set(
            "test", "basic", test_data, ttl=60, correlation_id=correlation_id
        )

        cached_data = self.cache.get("test", "basic", correlation_id=correlation_id)
        print(f"✅ Données récupérées: {cached_data}")

        # Test avec paramètres
        print("\n1.2 Test avec paramètres...")
        params = {"user_id": "123", "active": True}
        self.cache.set(
            "test",
            "with_params",
            test_data,
            ttl=60,
            params=params,
            correlation_id=correlation_id,
        )

        cached_with_params = self.cache.get(
            "test", "with_params", params=params, correlation_id=correlation_id
        )
        print(f"✅ Données avec paramètres: {cached_with_params}")

        # Test exists
        print("\n1.3 Test exists...")
        exists = self.cache.exists("test", "basic", correlation_id=correlation_id)
        print(f"✅ Key exists: {exists}")

        # Test delete
        print("\n1.4 Test delete...")
        deleted = self.cache.delete("test", "basic", correlation_id=correlation_id)
        print(f"✅ Key deleted: {deleted}")

        exists_after = self.cache.exists("test", "basic", correlation_id=correlation_id)
        print(f"✅ Key exists after delete: {exists_after}")

    def test_2_supabase_table_caching(self):
        """Test 2: Cache des données de table Supabase."""
        print("\n=== Test 2: Cache des données de table Supabase ===")
        correlation_id = get_correlation_id()

        # Test direct avec une table connue (scripts)
        print("2.1 Cache de données de la table 'scripts'...")
        start_time = time.time()

        table_cache_key = "table_scripts"
        cached_data = self.cache.get(
            "supabase", table_cache_key, correlation_id=correlation_id
        )

        if cached_data:
            print("✅ Données de table récupérées du cache!")
            scripts_data = cached_data
        else:
            print("📡 Récupération des données de scripts depuis Supabase...")
            try:
                # Récupérer quelques enregistrements de la table scripts
                scripts_data = self.supabase.query_records(
                    table="scripts", filters={}, limit=5, correlation_id=correlation_id
                )

                # Mettre en cache pour 5 minutes
                self.cache.set(
                    "supabase",
                    table_cache_key,
                    scripts_data,
                    ttl=300,
                    correlation_id=correlation_id,
                )
                print("✅ Données de scripts mises en cache!")

            except Exception as e:
                print(f"⚠️  Erreur lors de la récupération de scripts: {e}")
                scripts_data = []

        end_time = time.time()
        print(f"⏱️  Temps d'exécution: {(end_time - start_time)*1000:.2f}ms")
        print(
            f"📊 Nombre d'enregistrements: {len(scripts_data) if scripts_data else 0}"
        )

        # Tester avec filtres spécifiques
        print("\n2.2 Cache de données avec filtres...")
        start_time = time.time()

        filtered_cache_key = "scripts_active"
        cached_filtered = self.cache.get(
            "supabase", filtered_cache_key, correlation_id=correlation_id
        )

        if cached_filtered:
            print("✅ Données filtrées récupérées du cache!")
        else:
            print("📡 Récupération des scripts actifs depuis Supabase...")
            try:
                # Récupérer les scripts actifs
                filtered_data = self.supabase.query_records(
                    table="scripts",
                    filters={"is_active": True},
                    limit=3,
                    order_by="created_at",
                    desc=True,
                    correlation_id=correlation_id,
                )

                # Mettre en cache pour 2 minutes
                self.cache.set(
                    "supabase",
                    filtered_cache_key,
                    filtered_data,
                    ttl=120,
                    correlation_id=correlation_id,
                )
                print("✅ Scripts actifs mis en cache!")
                print(
                    f"📊 Nombre de scripts actifs: {len(filtered_data) if filtered_data else 0}"
                )

            except Exception as e:
                print(f"⚠️  Erreur lors de la récupération des scripts actifs: {e}")

        end_time = time.time()
        print(f"⏱️  Temps d'exécution filtres: {(end_time - start_time)*1000:.2f}ms")

    def test_3_query_result_caching(self):
        """Test 3: Cache des résultats de requêtes spécifiques."""
        print("\n=== Test 3: Cache des résultats de requêtes ===")
        correlation_id = get_correlation_id()

        # Tester avec la table scripts (qui devrait exister)
        print("3.1 Cache d'une requête avec filtres...")

        # Créer un hash pour la requête
        query_filters = {"is_active": True}
        query_string = f"scripts_query:{query_filters}"
        query_hash = hashlib.md5(query_string.encode()).hexdigest()[:16]

        start_time = time.time()

        # Vérifier le cache
        cached_result = self.cache.get(
            "supabase",
            f"query_{query_hash}",
            params=query_filters,
            correlation_id=correlation_id,
        )

        if cached_result:
            print("✅ Résultat de requête récupéré du cache!")
            scripts = cached_result
        else:
            print("📡 Exécution de la requête Supabase...")
            try:
                scripts = self.supabase.query_records(
                    table="scripts",
                    filters=query_filters,
                    limit=10,
                    correlation_id=correlation_id,
                )

                # Mettre en cache pour 2 minutes
                self.cache.set(
                    "supabase",
                    f"query_{query_hash}",
                    scripts,
                    ttl=120,
                    params=query_filters,
                    correlation_id=correlation_id,
                )
                print("✅ Résultat de requête mis en cache!")

            except Exception as e:
                print(f"⚠️  Erreur lors de l'exécution de la requête: {e}")
                scripts = []

        end_time = time.time()
        print(f"⏱️  Temps d'exécution: {(end_time - start_time)*1000:.2f}ms")
        print(f"📊 Nombre de scripts actifs: {len(scripts) if scripts else 0}")

    def test_4_decorator_caching(self):
        """Test 4: Cache avec décorateurs."""
        print("\n=== Test 4: Cache avec décorateurs ===")
        correlation_id = get_correlation_id()

        @self.cache.cached("api", "get_user_stats", ttl=180, key_params=["user_id"])
        def get_user_stats(user_id: str, correlation_id: Optional[str] = None):
            """Simule la récupération de statistiques utilisateur."""
            print(f"📡 Calcul des stats pour l'utilisateur {user_id}...")

            # Simuler une requête coûteuse (sync sleep)
            time.sleep(0.1)

            try:
                # Récupérer quelques données réelles de Supabase pour simulation
                scripts = self.supabase.query_records(
                    table="scripts",
                    filters={"is_active": True},
                    limit=3,
                    correlation_id=correlation_id,
                )

                return {
                    "user_id": user_id,
                    "total_scripts": len(scripts) if scripts else 0,
                    "last_updated": time.time(),
                    "sample_scripts": scripts[:2] if scripts else [],
                }
            except Exception as e:
                print(f"⚠️  Erreur dans get_user_stats: {e}")
                return {"user_id": user_id, "error": str(e)}

        # Premier appel (calcul + cache)
        print("4.1 Premier appel (mise en cache)...")
        start_time = time.time()
        stats1 = get_user_stats("user123", correlation_id=correlation_id)
        time1 = time.time() - start_time
        print(f"✅ Premier appel: {time1*1000:.2f}ms")

        # Deuxième appel (cache)
        print("\n4.2 Deuxième appel (depuis le cache)...")
        start_time = time.time()
        stats2 = get_user_stats("user123", correlation_id=correlation_id)
        time2 = time.time() - start_time
        print(f"✅ Deuxième appel: {time2*1000:.2f}ms")

        print(f"🚀 Accélération: {time1/time2:.1f}x plus rapide")
        print(f"📊 Stats: {stats2}")

    def test_5_cache_invalidation(self):
        """Test 5: Invalidation du cache."""
        print("\n=== Test 5: Invalidation du cache ===")
        correlation_id = get_correlation_id()

        # Créer plusieurs entrées de cache
        print("5.1 Création de plusieurs entrées de cache...")
        test_data = {"timestamp": time.time()}

        self.cache.set(
            "test_invalidation", "key1", test_data, correlation_id=correlation_id
        )
        self.cache.set(
            "test_invalidation", "key2", test_data, correlation_id=correlation_id
        )
        self.cache.set(
            "test_invalidation", "key3", test_data, correlation_id=correlation_id
        )
        self.cache.set(
            "other_namespace", "key1", test_data, correlation_id=correlation_id
        )

        print("✅ Entrées créées")

        # Vérifier qu'elles existent
        print("\n5.2 Vérification de l'existence...")
        exists1 = self.cache.exists(
            "test_invalidation", "key1", correlation_id=correlation_id
        )
        exists2 = self.cache.exists(
            "test_invalidation", "key2", correlation_id=correlation_id
        )
        exists_other = self.cache.exists(
            "other_namespace", "key1", correlation_id=correlation_id
        )
        print(f"✅ test_invalidation:key1 exists: {exists1}")
        print(f"✅ test_invalidation:key2 exists: {exists2}")
        print(f"✅ other_namespace:key1 exists: {exists_other}")

        # Invalidation par pattern
        print("\n5.3 Invalidation par pattern...")
        invalidated_count = self.cache.invalidate_pattern(
            "test_invalidation", "*", correlation_id=correlation_id
        )
        print(f"✅ {invalidated_count} entrées invalidées")

        # Vérifier l'invalidation
        print("\n5.4 Vérification après invalidation...")
        exists1_after = self.cache.exists(
            "test_invalidation", "key1", correlation_id=correlation_id
        )
        exists_other_after = self.cache.exists(
            "other_namespace", "key1", correlation_id=correlation_id
        )
        print(f"✅ test_invalidation:key1 exists après: {exists1_after}")
        print(f"✅ other_namespace:key1 exists après: {exists_other_after}")

    def test_6_different_data_types(self):
        """Test 6: Différents types de données."""
        print("\n=== Test 6: Différents types de données ===")
        correlation_id = get_correlation_id()

        # Test avec différents types
        test_cases = [
            ("string", "Simple string"),
            ("integer", 12345),
            ("float", 123.456),
            ("boolean", True),
            ("list", [1, 2, 3, "test", {"nested": True}]),
            ("dict", {"key": "value", "number": 42, "nested": {"deep": "value"}}),
            (
                "complex",
                {
                    "users": ["alice", "bob"],
                    "metadata": {"version": 1, "active": True},
                    "data": [{"id": 1, "name": "Test"}],
                },
            ),
        ]

        # Mettre en cache chaque type
        print("6.1 Test de mise en cache de différents types...")
        for data_type, data in test_cases:
            self.cache.set(
                "datatypes", data_type, data, ttl=60, correlation_id=correlation_id
            )
            print(f"✅ {data_type}: {type(data).__name__}")

        # Récupérer et vérifier chaque type
        print("\n6.2 Récupération et vérification...")
        for data_type, original_data in test_cases:
            cached_data = self.cache.get(
                "datatypes", data_type, correlation_id=correlation_id
            )

            if cached_data == original_data:
                print(f"✅ {data_type}: ✓ Identique")
            else:
                print(f"❌ {data_type}: ✗ Différent")
                print(f"   Original: {original_data}")
                print(f"   Cached:   {cached_data}")

    def test_7_cache_statistics(self):
        """Test 7: Statistiques du cache."""
        print("\n=== Test 7: Statistiques du cache ===")
        correlation_id = get_correlation_id()

        # Ajouter quelques données pour les stats
        self.cache.set(
            "stats_test", "item1", {"data": "test"}, correlation_id=correlation_id
        )
        self.cache.set(
            "stats_test", "item2", {"data": "test"}, correlation_id=correlation_id
        )
        self.cache.set(
            "supabase", "cached_query", {"results": []}, correlation_id=correlation_id
        )

        # Récupérer les statistiques
        print("7.1 Récupération des statistiques...")
        stats = self.cache.get_stats(correlation_id=correlation_id)

        print(f"✅ Nombre total de clés: {stats['total_keys']}")
        print("✅ Répartition par namespace:")
        for namespace, count in stats["namespaces"].items():
            print(f"   - {namespace}: {count} clés")

        # Test de santé
        print("\n7.2 Test de santé du cache...")
        is_healthy = self.cache.health_check(correlation_id=correlation_id)
        print(f"✅ Santé du cache: {'OK' if is_healthy else 'ERREUR'}")

    def test_8_performance_comparison(self):
        """Test 8: Comparaison de performance cache vs base de données."""
        print("\n=== Test 8: Comparaison de performance ===")
        correlation_id = get_correlation_id()

        query_key = "performance_test"

        # Mesurer le temps sans cache (direct Supabase)
        print("8.1 Requête directe Supabase (sans cache)...")
        times_direct = []

        for i in range(3):
            start_time = time.time()
            try:
                direct_result = self.supabase.query_records(
                    table="scripts",
                    filters={"is_active": True},
                    limit=5,
                    correlation_id=correlation_id,
                )
                end_time = time.time()
                times_direct.append((end_time - start_time) * 1000)
                print(f"   Essai {i+1}: {times_direct[-1]:.2f}ms")
            except Exception as e:
                print(f"   Erreur essai {i+1}: {e}")
                times_direct.append(0)

        avg_direct = sum(times_direct) / len(times_direct) if times_direct else 0

        # Mettre en cache
        print("\n8.2 Mise en cache du résultat...")
        try:
            cache_data = self.supabase.query_records(
                table="scripts",
                filters={"is_active": True},
                limit=5,
                correlation_id=correlation_id,
            )
            self.cache.set(
                "performance",
                query_key,
                cache_data,
                ttl=300,
                correlation_id=correlation_id,
            )
            print("✅ Données mises en cache")
        except Exception as e:
            print(f"⚠️  Erreur de mise en cache: {e}")
            cache_data = []

        # Mesurer le temps avec cache
        print("\n8.3 Requêtes depuis le cache...")
        times_cached = []

        for i in range(5):
            start_time = time.time()
            cached_result = self.cache.get(
                "performance", query_key, correlation_id=correlation_id
            )
            end_time = time.time()
            times_cached.append((end_time - start_time) * 1000)
            print(f"   Essai {i+1}: {times_cached[-1]:.2f}ms")

        avg_cached = sum(times_cached) / len(times_cached) if times_cached else 0

        # Comparaison
        print("\n8.4 Résultats de performance:")
        print(f"✅ Temps moyen Supabase direct: {avg_direct:.2f}ms")
        print(f"✅ Temps moyen cache Redis:     {avg_cached:.2f}ms")

        if avg_direct > 0 and avg_cached > 0:
            speedup = avg_direct / avg_cached
            print(f"🚀 Accélération: {speedup:.1f}x plus rapide avec le cache")

            if speedup > 10:
                print("🎯 Excellent! Le cache apporte un gain significatif")
            elif speedup > 5:
                print("👍 Bon gain de performance avec le cache")
            elif speedup > 2:
                print("✅ Gain modéré mais utile")
            else:
                print("⚠️  Gain faible - vérifier la configuration")

    def run_all_tests(self):
        """Exécute tous les tests."""
        print("🚀 === TEST COMPLET DU CACHE REDIS AVEC SUPABASE ===")

        try:
            self.test_1_basic_cache_operations()
            self.test_2_supabase_table_caching()
            self.test_3_query_result_caching()
            self.test_4_decorator_caching()
            self.test_5_cache_invalidation()
            self.test_6_different_data_types()
            self.test_7_cache_statistics()
            self.test_8_performance_comparison()

            print("\n🎉 === TOUS LES TESTS TERMINÉS AVEC SUCCÈS ===")

        except Exception as e:
            print(f"\n❌ Erreur lors des tests: {e}")
            self.logger.log_exception(e, {"correlation_id": get_correlation_id()})

        finally:
            # Nettoyer
            print("\n🧹 Nettoyage du cache de test...")
            try:
                self.cache.invalidate_pattern("test", "*")
                self.cache.invalidate_pattern("datatypes", "*")
                self.cache.invalidate_pattern("stats_test", "*")
                self.cache.invalidate_pattern("performance", "*")
                self.cache.close()
                print("✅ Nettoyage terminé")
            except Exception as e:
                print(f"⚠️  Erreur lors du nettoyage: {e}")


def main():
    """Point d'entrée principal."""
    tester = CacheTester()
    tester.run_all_tests()


if __name__ == "__main__":
    main()
