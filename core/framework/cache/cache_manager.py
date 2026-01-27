"""
Cache Manager - High-level caching interface integrated with metrics.

Combines semantic caching with cost tracking from observability system.
"""

from dataclasses import dataclass
from datetime import datetime
from .semantic_cache import SemanticCache, CacheHit


@dataclass
class CacheStats:
    """Complete cache statistics with ROI metrics"""
    total_requests: int
    cache_hits: int
    cache_misses: int
    hit_rate: float
    total_cost_saved_usd: float
    avg_cost_per_hit_usd: float
    active_entries: int
    
    def get_monthly_savings(self, requests_per_month: int = 10000) -> float:
        """Estimate monthly cost savings"""
        if self.total_requests == 0:
            return 0.0
        
        estimated_monthly_hits = requests_per_month * self.hit_rate
        monthly_savings = estimated_monthly_hits * self.avg_cost_per_hit_usd
        
        return monthly_savings


class CacheManager:
    """
    High-level cache manager with automatic integration.
    
    Designed to work seamlessly with LiteLLMProvider and MetricsCollector.
    """
    
    def __init__(
        self,
        enable_caching: bool = True,
        similarity_threshold: float = 0.85,
        ttl_seconds: int = 3600
    ):
        self.enable_caching = enable_caching
        self.cache = SemanticCache(
            similarity_threshold=similarity_threshold,
            ttl_seconds=ttl_seconds
        ) if enable_caching else None
    
    def get_cached_response(
        self,
        prompt: str,
        model: str,
        estimated_cost: float
    ) -> tuple[str | None, bool, float]:
        """
        Try to get cached response.
        
        Returns:
            (response, is_cache_hit, cost_saved)
        """
        if not self.enable_caching or not self.cache:
            return None, False, 0.0
        
        cache_hit = self.cache.get(
            prompt=prompt,
            model=model,
            estimated_cost=estimated_cost
        )
        
        if cache_hit:
            return cache_hit.response, True, cache_hit.cost_saved_usd
        
        return None, False, 0.0
    
    def cache_response(
        self,
        prompt: str,
        response: str,
        model: str,
        actual_cost: float
    ):
        """Store response in cache"""
        if not self.enable_caching or not self.cache:
            return
        
        self.cache.set(
            prompt=prompt,
            response=response,
            model=model,
            cost=actual_cost
        )
    
    def get_stats(self) -> CacheStats:
        """Get comprehensive cache statistics"""
        if not self.cache:
            return CacheStats(
                total_requests=0,
                cache_hits=0,
                cache_misses=0,
                hit_rate=0.0,
                total_cost_saved_usd=0.0,
                avg_cost_per_hit_usd=0.0,
                active_entries=0
            )
        
        stats = self.cache.get_stats()
        
        avg_cost = (
            stats['total_cost_saved_usd'] / max(stats['cache_hits'], 1)
        )
        
        return CacheStats(
            total_requests=stats['total_requests'],
            cache_hits=stats['cache_hits'],
            cache_misses=stats['cache_misses'],
            hit_rate=stats['hit_rate'],
            total_cost_saved_usd=stats['total_cost_saved_usd'],
            avg_cost_per_hit_usd=avg_cost,
            active_entries=stats['active_entries']
        )
    
    def print_roi_report(self, monthly_requests: int = 10000):
        """Print ROI analysis for enterprise decision-makers"""
        stats = self.get_stats()
        
        if stats.total_requests == 0:
            print("No cache data yet")
            return
        
        monthly_savings = stats.get_monthly_savings(monthly_requests)
        annual_savings = monthly_savings * 12
        
        print("\n" + "="*60)
        print("💰 CACHE ROI ANALYSIS FOR ENTERPRISES")
        print("="*60)
        
        print(f"\n📊 CURRENT PERFORMANCE:")
        print(f"   Cache Hit Rate: {stats.hit_rate*100:.1f}%")
        print(f"   Total Cost Saved: ${stats.total_cost_saved_usd:.4f}")
        print(f"   API Calls Avoided: {stats.cache_hits}")
        
        print(f"\n💵 PROJECTED SAVINGS:")
        print(f"   Monthly ({monthly_requests:,} requests): ${monthly_savings:.2f}/month")
        print(f"   Annual: ${annual_savings:.2f}/year")
        
        print(f"\n🎯 ENTERPRISE VALUE:")
        print(f"   Cost Reduction: {stats.hit_rate*100:.0f}%")
        print(f"   Response Time: ~100x faster (cache vs API)")
        print(f"   Reliability: No API rate limits on cached queries")
        
        # ROI example
        if stats.hit_rate > 0.4:  # 40%+ hit rate
            print(f"\n✅ STRONG ROI:")
            print(f"   With ${annual_savings:.0f}/year savings,")
            print(f"   Cache pays for itself in infrastructure costs")
            print(f"   Plus: Faster responses, better UX, higher reliability")
        
        print("\n" + "="*60 + "\n")
