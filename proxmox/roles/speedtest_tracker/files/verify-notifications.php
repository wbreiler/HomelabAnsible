<?php
// Run inside the pinned application's /app/www directory. No data writes or sends.
require 'vendor/autoload.php';
$app = require 'bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
function check(bool $condition, string $message): void {
    if (!$condition) {
        throw new RuntimeException($message);
    }
}
$n = clone app(App\Settings\NotificationSettings::class);
$t = app(App\Settings\ThresholdSettings::class);
check($n->apprise_enabled && !$n->apprise_on_speedtest_run && $n->apprise_on_threshold_failure, 'Notification triggers');
check($t->absolute_enabled && $t->absolute_ping === null, 'Only speed thresholds should be enabled');
foreach ([$t->absolute_download, $t->absolute_upload] as $limit) {
    foreach ([[-0.1, false], [0, true], [0.1, true]] as [$offset, $expected]) {
        $passed = App\Helpers\Benchmark::bitrate(($limit + $offset) * 1000000 / 8, ['value' => $limit, 'unit' => 'mbps']);
        check($passed === $expected, 'Threshold boundary');
    }
}
$n->database_enabled = false;
$n->mail_enabled = false;
$n->webhook_enabled = false;
$result = App\Models\Result::latest('id')->firstOrFail()->replicate();
$result->scheduled = true;
$result->healthy = true;
Illuminate\Support\Facades\Notification::fake();
(new App\Listeners\ProcessCompletedSpeedtest($n))->handle(new App\Events\SpeedtestCompleted($result));
check(count(Illuminate\Support\Facades\Notification::sentNotifications()) === 0, 'Healthy result must be silent');
$result->healthy = false;
$result->benchmarks = ['download' => ['passed' => false, 'benchmark_value' => $t->absolute_download, 'unit' => 'mbps']];
(new App\Listeners\ProcessUnhealthySpeedtest($n))->handle(new App\Events\SpeedtestBenchmarkUnhealthy($result));
check(count(Illuminate\Support\Facades\Notification::sentNotifications()) === 1, 'Below-threshold result must notify');
echo "PASS: six boundary checks, healthy result silent, threshold result notifies (delivery faked).\n";
