//! In-process background job scheduler for the single-operator desktop.
//!
//! There is no external queue: one Tokio task owns three [`tokio::time`] intervals
//! (retention sweep, offer sweep, backup + audit verification) and drives a
//! [`JobBackend`]. A failing job is logged and the loop continues; signalling
//! `true` on the shutdown channel (see [`shutdown_trigger`]) stops the loop.
//!
//! [`AppService`] is adapted via [`JobBackend`] rather than shared directly, so
//! the Tauri command layer keeps exclusive ownership of its instance and hands
//! the scheduler whatever backend it chooses (usually a second handle behind
//! `Arc<tokio::sync::Mutex<..>>`).

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use hragents_core::time::BusinessDate;

use super::AppService;

/// Destination-agnostic background work. Returning `Err` logs the failure and
/// the loop carries on with the next tick; nothing here is allowed to panic.
pub trait JobBackend: Send {
    /// Compute retention-due items; returns how many are due.
    fn run_retention_sweep(&mut self) -> Result<usize, String>;
    /// Expire past-due offers; returns how many were expired.
    fn run_offer_sweep(&mut self) -> Result<usize, String>;
    /// Write a backup without a caller-chosen destination; the scheduler
    /// routes through [`JobBackend::run_backup_to`] when it has a directory.
    fn run_backup(&mut self) -> Result<u64, String>;
    /// Verify the audit hash chain; returns the entry count.
    fn verify_audit(&self) -> Result<usize, String>;
    /// Write a backup to `dest`. The default delegates to [`JobBackend::run_backup`];
    /// the scheduler always prefers this method when `backup_dir` is set.
    fn run_backup_to(&mut self, dest: &Path) -> Result<u64, String> {
        let _ = dest;
        self.run_backup()
    }
}

impl JobBackend for AppService {
    fn run_retention_sweep(&mut self) -> Result<usize, String> {
        self.retention_sweep(BusinessDate::today())
            .map(|due| due.len())
            .map_err(|error| error.to_string())
    }

    fn run_offer_sweep(&mut self) -> Result<usize, String> {
        self.sweep_expired_offers(BusinessDate::today())
            .map_err(|error| error.to_string())
    }

    fn run_backup(&mut self) -> Result<u64, String> {
        Err("backup directory is not configured".to_owned())
    }

    fn run_backup_to(&mut self, dest: &Path) -> Result<u64, String> {
        self.backup(dest).map_err(|error| error.to_string())
    }

    fn verify_audit(&self) -> Result<usize, String> {
        self.audit_verify()
            .map(|verification| verification.entries)
            .map_err(|error| error.to_string())
    }
}

/// How often each background job runs, plus where automatic backups go.
#[derive(Debug, Clone)]
pub struct SchedulerConfig {
    /// Seconds between retention sweeps.
    pub retention_interval_secs: u64,
    /// Seconds between expired-offer sweeps.
    pub offer_sweep_interval_secs: u64,
    /// Seconds between backup ticks.
    pub backup_interval_secs: u64,
    /// When `None`, the backup job (file write) is skipped.
    pub backup_dir: Option<PathBuf>,
}

impl Default for SchedulerConfig {
    fn default() -> Self {
        Self {
            retention_interval_secs: 6 * 60 * 60,
            offer_sweep_interval_secs: 60 * 60,
            backup_interval_secs: 24 * 60 * 60,
            backup_dir: None,
        }
    }
}

/// A zero interval selects a 10 ms test tick so unit tests can observe the
/// loop without waiting out production intervals. Production configs use the
/// [`SchedulerConfig::default`] values (hours), never zero.
fn interval_duration(secs: u64) -> Duration {
    if secs == 0 {
        Duration::from_millis(10)
    } else {
        Duration::from_secs(secs)
    }
}

fn backup_path(dir: &Path) -> PathBuf {
    dir.join(format!("hragents-auto-{}.db", BusinessDate::today()))
}

/// Build the shutdown channel. The scheduler stops once `true` is sent (or
/// all senders are dropped).
pub fn shutdown_trigger() -> (
    tokio::sync::watch::Sender<bool>,
    tokio::sync::watch::Receiver<bool>,
) {
    tokio::sync::watch::channel(false)
}

/// Handle for the spawned scheduler task. The worker runs detached; dropping
/// this handle does not stop it — send `true` on the shutdown channel.
pub struct Scheduler {
    config: SchedulerConfig,
    shutdown: tokio::sync::watch::Receiver<bool>,
}

impl Scheduler {
    /// Spawn the background loop driving `backend`. Each job runs inline on
    /// the scheduler task when its interval ticks; failures are logged with
    /// `eprintln!` and never break the loop.
    pub fn spawn(
        backend: Arc<tokio::sync::Mutex<dyn JobBackend>>,
        config: SchedulerConfig,
        shutdown: tokio::sync::watch::Receiver<bool>,
    ) -> Self {
        let worker_backend = Arc::clone(&backend);
        let worker_config = config.clone();
        let mut worker_shutdown = shutdown.clone();
        tokio::spawn(async move {
            run_loop(worker_backend, &worker_config, &mut worker_shutdown).await;
        });
        Self { config, shutdown }
    }

    /// The config this scheduler was spawned with.
    pub fn config(&self) -> &SchedulerConfig {
        &self.config
    }

    /// Returns true once the shutdown channel has flipped to `true`.
    pub fn is_shutdown(&self) -> bool {
        *self.shutdown.borrow()
    }
}

async fn run_loop(
    backend: Arc<tokio::sync::Mutex<dyn JobBackend>>,
    config: &SchedulerConfig,
    shutdown: &mut tokio::sync::watch::Receiver<bool>,
) {
    let mut retention = tokio::time::interval(interval_duration(config.retention_interval_secs));
    let mut offers = tokio::time::interval(interval_duration(config.offer_sweep_interval_secs));
    let mut backup = tokio::time::interval(interval_duration(config.backup_interval_secs));
    for tick in [&mut retention, &mut offers, &mut backup] {
        tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    }
    loop {
        tokio::select! {
            result = shutdown.changed() => {
                if result.is_err() || *shutdown.borrow_and_update() {
                    break;
                }
            }
            _ = retention.tick() => {
                let mut backend = backend.lock().await;
                match backend.run_retention_sweep() {
                    Ok(due) => eprintln!("[scheduler] retention_sweep: {due} due"),
                    Err(error) => eprintln!("[scheduler] retention_sweep failed: {error}"),
                }
            }
            _ = offers.tick() => {
                let mut backend = backend.lock().await;
                match backend.run_offer_sweep() {
                    Ok(expired) => eprintln!("[scheduler] offer_sweep: {expired} expired"),
                    Err(error) => eprintln!("[scheduler] offer_sweep failed: {error}"),
                }
            }
            _ = backup.tick() => {
                if let Some(dir) = config.backup_dir.clone() {
                    if let Err(error) = std::fs::create_dir_all(&dir) {
                        eprintln!("[scheduler] backup failed: {error}");
                    } else {
                        let path = backup_path(&dir);
                        let mut backend = backend.lock().await;
                        match backend.run_backup_to(&path) {
                            Ok(bytes) => eprintln!(
                                "[scheduler] backup: wrote {bytes} bytes to {}",
                                path.display()
                            ),
                            Err(error) => eprintln!("[scheduler] backup failed: {error}"),
                        }
                        drop(backend);
                    }
                } else {
                    eprintln!("[scheduler] backup skipped: no backup_dir configured");
                }
                let backend = backend.lock().await;
                match backend.verify_audit() {
                    Ok(entries) => eprintln!("[scheduler] audit_verify: {entries} entries ok"),
                    Err(error) => eprintln!("[scheduler] audit_verify failed: {error}"),
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    struct FakeBackend {
        retention_calls: Arc<AtomicUsize>,
        offer_calls: Arc<AtomicUsize>,
        backup_calls: Arc<AtomicUsize>,
        verify_calls: Arc<AtomicUsize>,
        retention_failures: AtomicUsize,
    }

    impl FakeBackend {
        fn new() -> Self {
            Self {
                retention_calls: Arc::new(AtomicUsize::new(0)),
                offer_calls: Arc::new(AtomicUsize::new(0)),
                backup_calls: Arc::new(AtomicUsize::new(0)),
                verify_calls: Arc::new(AtomicUsize::new(0)),
                retention_failures: AtomicUsize::new(0),
            }
        }

        fn counts(&self) -> (usize, usize, usize, usize) {
            (
                self.retention_calls.load(Ordering::SeqCst),
                self.offer_calls.load(Ordering::SeqCst),
                self.backup_calls.load(Ordering::SeqCst),
                self.verify_calls.load(Ordering::SeqCst),
            )
        }
    }

    impl JobBackend for FakeBackend {
        fn run_retention_sweep(&mut self) -> Result<usize, String> {
            self.retention_calls.fetch_add(1, Ordering::SeqCst);
            if self.retention_failures.load(Ordering::SeqCst) > 0 {
                self.retention_failures.fetch_sub(1, Ordering::SeqCst);
                return Err("boom".to_owned());
            }
            Ok(0)
        }

        fn run_offer_sweep(&mut self) -> Result<usize, String> {
            self.offer_calls.fetch_add(1, Ordering::SeqCst);
            Ok(0)
        }

        fn run_backup(&mut self) -> Result<u64, String> {
            self.backup_calls.fetch_add(1, Ordering::SeqCst);
            Ok(42)
        }

        fn verify_audit(&self) -> Result<usize, String> {
            self.verify_calls.fetch_add(1, Ordering::SeqCst);
            Ok(7)
        }
    }

    fn test_config() -> SchedulerConfig {
        SchedulerConfig {
            retention_interval_secs: 0,
            offer_sweep_interval_secs: 0,
            backup_interval_secs: 0,
            backup_dir: Some(std::env::temp_dir()),
        }
    }

    async fn wait_until(message: &str, mut done: impl FnMut() -> bool) {
        tokio::time::timeout(Duration::from_secs(5), async {
            while !done() {
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
        })
        .await
        .unwrap_or_else(|_| panic!("timed out waiting for {message}"));
    }

    #[test]
    fn defaults_use_expected_intervals() {
        let config = SchedulerConfig::default();
        assert_eq!(config.retention_interval_secs, 6 * 60 * 60);
        assert_eq!(config.offer_sweep_interval_secs, 60 * 60);
        assert_eq!(config.backup_interval_secs, 24 * 60 * 60);
        assert!(config.backup_dir.is_none());
    }

    #[tokio::test]
    async fn intervals_fire() {
        let backend = Arc::new(tokio::sync::Mutex::new(FakeBackend::new()));
        let counts = Arc::clone(&backend);
        let (_tx, rx) = shutdown_trigger();
        let _scheduler = Scheduler::spawn(backend, test_config(), rx);
        wait_until("all jobs ticking", || {
            let guard = counts.try_lock();
            match guard {
                Ok(backend) => {
                    let (retention, offers, backup, verify) = backend.counts();
                    retention >= 2 && offers >= 2 && backup >= 2 && verify >= 1
                }
                Err(_) => false,
            }
        })
        .await;
    }

    #[tokio::test]
    async fn shutdown_stops_ticks() {
        let backend = Arc::new(tokio::sync::Mutex::new(FakeBackend::new()));
        let counts = Arc::clone(&backend);
        let (tx, rx) = shutdown_trigger();
        let _scheduler = Scheduler::spawn(backend, test_config(), rx);
        wait_until("first ticks", || {
            counts
                .try_lock()
                .is_ok_and(|backend| backend.counts().0 >= 2)
        })
        .await;
        tx.send(true).expect("shutdown receiver alive");
        tokio::time::sleep(Duration::from_millis(50)).await;
        let frozen = counts.lock().await.counts();
        tokio::time::sleep(Duration::from_millis(100)).await;
        assert_eq!(counts.lock().await.counts(), frozen);
    }

    #[tokio::test]
    async fn failing_job_does_not_kill_loop() {
        let backend = Arc::new(tokio::sync::Mutex::new(FakeBackend::new()));
        backend
            .lock()
            .await
            .retention_failures
            .store(1, Ordering::SeqCst);
        let counts = Arc::clone(&backend);
        let (_tx, rx) = shutdown_trigger();
        let _scheduler = Scheduler::spawn(backend, test_config(), rx);
        // The first retention tick fails; later ticks must still run.
        wait_until("retention recovered after failure", || {
            counts
                .try_lock()
                .is_ok_and(|backend| backend.counts().0 >= 3)
        })
        .await;
        wait_until("other jobs kept ticking", || {
            counts.try_lock().is_ok_and(|backend| {
                let (_, offers, backup, _) = backend.counts();
                offers >= 1 && backup >= 1
            })
        })
        .await;
    }

    #[tokio::test]
    async fn backup_skipped_without_dir() {
        let backend = Arc::new(tokio::sync::Mutex::new(FakeBackend::new()));
        let counts = Arc::clone(&backend);
        let config = SchedulerConfig {
            backup_dir: None,
            ..test_config()
        };
        let (_tx, rx) = shutdown_trigger();
        let _scheduler = Scheduler::spawn(backend, config, rx);
        wait_until("sweeps ticking without backup_dir", || {
            counts.try_lock().is_ok_and(|backend| {
                let (retention, offers, _, _) = backend.counts();
                retention >= 2 && offers >= 2
            })
        })
        .await;
        tokio::time::sleep(Duration::from_millis(50)).await;
        let (_, _, backup, verify) = counts.lock().await.counts();
        assert_eq!(backup, 0);
        assert!(verify >= 1);
    }
}
