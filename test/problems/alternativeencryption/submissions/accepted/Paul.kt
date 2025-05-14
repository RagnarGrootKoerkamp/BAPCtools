import java.util.*

fun main() {
    readln()
    for (i in 1..readln().toInt()) {
        println(readln().trim().map { (((it.code - 1) xor 1) + 1).toChar() }.joinToString(""))
    }
}
