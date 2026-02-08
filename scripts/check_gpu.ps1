$gpu = Get-PnpDevice -Class Display | Where-Object { $_.FriendlyName -like '*NVIDIA*' }
if ($gpu) {
    Write-Host "=== NVIDIA GPU Found ==="
    Write-Host "Name: $($gpu.FriendlyName)"
    Write-Host "Status: $($gpu.Status)"
    Write-Host "InstanceId: $($gpu.InstanceId)"
    Write-Host "Problem: $($gpu.Problem)"
    Write-Host "ConfigManagerErrorCode: $($gpu.ConfigManagerErrorCode)"
    Write-Host ""

    if ($gpu.Status -eq 'Unknown' -or $gpu.Status -eq 'Error' -or $gpu.Status -ne 'OK') {
        Write-Host "GPU is NOT working properly!"
        Write-Host "Attempting to enable/restart the device..."
        Write-Host ""
        Write-Host "Run this command as Administrator to re-enable:"
        Write-Host "  Enable-PnpDevice -InstanceId '$($gpu.InstanceId)' -Confirm:`$false"
        Write-Host ""
        Write-Host "Or try disabling and re-enabling:"
        Write-Host "  Disable-PnpDevice -InstanceId '$($gpu.InstanceId)' -Confirm:`$false"
        Write-Host "  Enable-PnpDevice -InstanceId '$($gpu.InstanceId)' -Confirm:`$false"
    }
} else {
    Write-Host "No NVIDIA GPU found in system!"
}

Write-Host ""
Write-Host "=== All Display Devices ==="
Get-PnpDevice -Class Display | Format-Table Status, FriendlyName, InstanceId -AutoSize

Write-Host "=== NVIDIA Driver Files ==="
$driverPath = "C:\Windows\System32\drivers\nvlddmkm.sys"
if (Test-Path $driverPath) {
    $info = Get-Item $driverPath
    Write-Host "Driver file exists: $driverPath"
    Write-Host "Size: $($info.Length) bytes"
    Write-Host "Last modified: $($info.LastWriteTime)"
} else {
    Write-Host "NVIDIA driver file NOT found at $driverPath"
}
